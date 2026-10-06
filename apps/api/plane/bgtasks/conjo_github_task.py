# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Process GitHub webhooks: link branches, commits and pull requests to work items.

Also runs smart commits (``MAN-12 #comment ...``, ``MAN-12 #done``), the per-project
pull request automations and the pull request notices in the project's chat room.
"""

# Python imports
import json
import logging
import uuid
from datetime import timedelta

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import escape

# Module imports
from plane.utils.conjo_chat import MatrixRetryableError, send_html_message
from plane.utils.conjo_chat import is_configured as chat_is_configured
from plane.utils.conjo_github import find_keys, parse_smart_commands, resolve_state
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")

LAST_EVENT_CACHE_KEY = "conjo_github:last_event"
BOT_USERNAME = "conjo_github_bot"
CLOSED_GROUPS = ("completed", "cancelled")


# --------------------------------------------------------------------------- #
# Payload compaction (runs in the web request, keeps Celery messages small)
# --------------------------------------------------------------------------- #


def _repo(payload):
    repo = payload.get("repository") or {}
    return {"full_name": repo.get("full_name") or "", "html_url": repo.get("html_url") or ""}


def _sender(payload):
    sender = payload.get("sender") or {}
    return {"login": sender.get("login") or "", "id": sender.get("id"), "avatar_url": sender.get("avatar_url") or ""}


def compact_payload(event, payload):
    """Keep only the fields the worker needs; ``None`` for events we ignore."""
    base = {"repository": _repo(payload), "sender": _sender(payload)}
    if event == "push":
        base.update(
            ref=payload.get("ref") or "",
            deleted=bool(payload.get("deleted")),
            commits=[
                {
                    "id": c.get("id") or "",
                    "message": (c.get("message") or "")[:4000],
                    "url": c.get("url") or "",
                    "timestamp": c.get("timestamp"),
                    "author": {
                        "name": (c.get("author") or {}).get("name") or "",
                        "email": (c.get("author") or {}).get("email") or "",
                        "username": (c.get("author") or {}).get("username") or "",
                    },
                }
                for c in (payload.get("commits") or [])[:50]
            ],
        )
        return base
    if event in ("create", "delete"):
        if payload.get("ref_type") != "branch":
            return None
        base.update(ref=payload.get("ref") or "")
        return base
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        user = pr.get("user") or {}
        base.update(
            action=payload.get("action") or "",
            number=pr.get("number") or payload.get("number"),
            title=pr.get("title") or "",
            body=(pr.get("body") or "")[:8000],
            html_url=pr.get("html_url") or "",
            state=pr.get("state") or "",
            merged=bool(pr.get("merged")),
            draft=bool(pr.get("draft")),
            head=(pr.get("head") or {}).get("ref") or "",
            base=(pr.get("base") or {}).get("ref") or "",
            updated_at=pr.get("updated_at"),
            user={"login": user.get("login") or "", "id": user.get("id"), "avatar_url": user.get("avatar_url") or ""},
        )
        return base
    return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def get_workspace():
    from plane.db.models import Workspace

    return Workspace.objects.filter(slug=settings.CONJO_GITHUB_WORKSPACE_SLUG).first()


def resolve_issues(workspace_id, keys):
    """Return the existing work items for ``[(IDENT, seq)]`` keys, in order."""
    from plane.db.models import Issue, Project

    if not keys:
        return []
    idents = {ident for ident, _ in keys}
    projects = {
        p.identifier.upper(): p for p in Project.objects.filter(workspace_id=workspace_id, identifier__in=idents)
    }
    issues = []
    for ident, seq in keys:
        project = projects.get(ident)
        if project is None:
            continue
        issue = (
            Issue.objects.filter(project=project, sequence_id=seq)
            .select_related("project", "state", "workspace")
            .first()
        )
        if issue is not None and issue not in issues:
            issues.append(issue)
    return issues


def user_for(workspace_id, email=None, github_id=None):
    """Map a GitHub author to a workspace member (by email, or by GitHub login account)."""
    from plane.db.models import Account, User

    members = User.objects.filter(
        is_active=True,
        is_bot=False,
        member_workspace__workspace_id=workspace_id,
        member_workspace__is_active=True,
    )
    if email and not email.lower().endswith("users.noreply.github.com"):
        user = members.filter(email__iexact=email).first()
        if user is not None:
            return user
    if github_id:
        account = Account.objects.filter(provider="github", provider_account_id=str(github_id)).first()
        if account is not None:
            return members.filter(pk=account.user_id).first()
    return None


def get_bot_user():
    """The "GitHub" bot that acts for automations when the author has no Tasks account."""
    from urllib.parse import urlparse

    from plane.db.models import User

    bot = User.objects.filter(username=BOT_USERNAME).first()
    if bot is not None:
        return bot
    host = urlparse(settings.TASKS_PUBLIC_URL).hostname or "tasks.local"
    try:
        return User.objects.create(
            username=BOT_USERNAME,
            display_name="GitHub",
            first_name="GitHub",
            last_name="",
            is_bot=True,
            bot_type="CONJO_GITHUB",
            email=f"github-bot@{host}",
            password=make_password(uuid.uuid4().hex),
            is_password_autoset=True,
        )
    except IntegrityError:
        return User.objects.filter(username=BOT_USERNAME).first()


def get_project_settings(project_id):
    from plane.db.models import ProjectGitHubSettings

    return (
        ProjectGitHubSettings.objects.filter(project_id=project_id)
        .select_related("pr_opened_state", "pr_merged_state")
        .first()
    )


def upsert_link(issue, kind, repository, external_id, fields, create_only=False):
    """Create or update a development link (only create with ``create_only``). Returns ``(link, created)``."""
    from plane.db.models import IssueDevelopmentLink

    lookup = {
        "issue": issue,
        "provider": "github",
        "kind": kind,
        "repository": repository,
        "external_id": str(external_id),
    }
    link = IssueDevelopmentLink.objects.filter(**lookup).first()
    if link is not None and create_only:
        return link, False
    if link is not None:
        for key, value in fields.items():
            setattr(link, key, value)
        link.save()
        return link, False
    try:
        link = IssueDevelopmentLink.objects.create(project_id=issue.project_id, **lookup, **fields)
        return link, True
    except IntegrityError:
        # Another delivery for the same object won the race.
        return IssueDevelopmentLink.objects.filter(**lookup).first(), False


def parse_time(value):
    parsed = parse_datetime(value) if isinstance(value, str) else None
    return parsed or timezone.now()


def change_state(issue, state, actor):
    """Move ``issue`` to ``state`` and record it like a manual change (activity + notices)."""
    from plane.bgtasks.issue_activities_task import issue_activity

    if state is None or state.id == issue.state_id:
        return False
    old_state_id = issue.state_id
    issue.state = state
    issue.save(update_fields=["state", "updated_at"])
    issue_activity.delay(
        type="issue.activity.updated",
        requested_data=json.dumps({"state_id": str(state.id)}),
        current_instance=json.dumps({"state_id": str(old_state_id) if old_state_id else None}),
        issue_id=str(issue.id),
        actor_id=str(actor.id),
        project_id=str(issue.project_id),
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=settings.TASKS_PUBLIC_URL,
    )
    return True


def add_comment(issue, actor, text, commit_url, short_sha, repository):
    from django.core.serializers.json import DjangoJSONEncoder

    from plane.app.serializers import IssueCommentSerializer
    from plane.bgtasks.issue_activities_task import issue_activity
    from plane.db.models import IssueComment

    html = (
        f"<p>{escape(text)}</p>"
        f'<p><em>via commit <a href="{escape(commit_url)}">{escape(short_sha)}</a> em {escape(repository)}</em></p>'
    )
    comment = IssueComment.objects.create(
        issue=issue,
        project_id=issue.project_id,
        actor=actor,
        comment_html=html,
        comment_stripped=text,
        external_source="github",
        external_id=short_sha,
    )
    issue_activity.delay(
        type="comment.activity.created",
        requested_data=json.dumps(IssueCommentSerializer(comment).data, cls=DjangoJSONEncoder),
        actor_id=str(actor.id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=None,
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=settings.TASKS_PUBLIC_URL,
    )


def log_commit_time(issue, actor, duration, short_sha, repository):
    """``MAN-12 #time 1h30``: time spent, once per commit."""
    from plane.db.models import IssueWorkLog
    from plane.utils.conjo_billing import parse_duration, today

    minutes = parse_duration(duration)
    if not minutes or minutes > 24 * 60:
        return
    IssueWorkLog.objects.get_or_create(
        issue=issue,
        source=IssueWorkLog.SOURCE_COMMIT,
        external_id=short_sha,
        defaults={
            "project_id": issue.project_id,
            "member": actor,
            "minutes": minutes,
            "logged_on": today(),
            "description": f"via commit {short_sha} em {repository}",
        },
    )


def apply_smart_commands(issue, commands, actor, commit_url, short_sha, repository):
    from plane.db.models import State

    project_settings = get_project_settings(issue.project_id)
    if project_settings is not None and not project_settings.smart_commits:
        return
    for text in commands.get("comments", []):
        add_comment(issue, actor, text, commit_url, short_sha, repository)
    for duration in commands.get("times", []):
        log_commit_time(issue, actor, duration, short_sha, repository)
    states = list(State.objects.filter(project_id=issue.project_id))
    for command in commands.get("transitions", []):
        state = resolve_state(states, command)
        if state is not None:
            change_state(issue, state, actor)


# --------------------------------------------------------------------------- #
# Event handlers
# --------------------------------------------------------------------------- #


def handle_branch(workspace, data, deleted=False, quiet=False):
    from plane.db.models import IssueDevelopmentLink

    repository = data["repository"]["full_name"]
    branch = data["ref"]
    if branch.startswith("refs/heads/"):
        branch = branch[len("refs/heads/") :]
    if deleted:
        IssueDevelopmentLink.objects.filter(
            provider="github",
            kind="branch",
            repository=repository,
            external_id=branch,
            workspace_id=workspace.id,
        ).update(state="deleted", updated_at=timezone.now())
        return
    sender = data["sender"]
    for issue in resolve_issues(workspace.id, find_keys(branch, any_case=True)):
        upsert_link(
            issue,
            "branch",
            repository,
            branch,
            {
                "title": branch,
                "url": f"{data['repository']['html_url']}/tree/{branch}",
                "state": "open",
                "author_login": sender["login"],
                "author_avatar_url": sender["avatar_url"],
                "event_at": timezone.now(),
            },
            # A history sync must not move a branch's date or author on every run.
            create_only=quiet,
        )


def handle_push(workspace, data):
    ref = data["ref"]
    if not ref.startswith("refs/heads/"):
        return
    if data["deleted"]:
        handle_branch(workspace, data, deleted=True)
        return
    handle_branch(workspace, data)

    link_commits(workspace, data["repository"]["full_name"], ref[len("refs/heads/") :], data["commits"])


def link_commits(workspace, repository, branch, commits, quiet=False):
    """Link commits that mention work items; smart commands run unless ``quiet`` (history sync)."""
    for commit in commits:
        message = commit["message"]
        keys = find_keys(message)
        if not keys:
            continue
        sha = commit["id"]
        short_sha = sha[:7]
        author = commit["author"]
        smart = parse_smart_commands(message)
        actor = None
        for issue in resolve_issues(workspace.id, keys):
            _, created = upsert_link(
                issue,
                "commit",
                repository,
                sha,
                {
                    "title": message.splitlines()[0][:500] if message else short_sha,
                    "url": commit["url"],
                    "state": "",
                    "author_login": author["username"],
                    "author_name": author["name"],
                    "event_at": parse_time(commit["timestamp"]),
                    "metadata": {"branch": branch, "message": message[:2000]},
                },
            )
            # Commands run once per commit, even if it is pushed to other branches later.
            commands = smart.get((issue.project.identifier.upper(), issue.sequence_id))
            if quiet or not created or not commands:
                continue
            if actor is None:
                actor = user_for(workspace.id, email=author["email"]) or False
            if actor:
                apply_smart_commands(issue, commands, actor, commit["url"], short_sha, repository)
            else:
                logger.info(
                    "conjo_github: smart commit %s ignored, author %s has no account", short_sha, author["email"]
                )


def pr_state(data):
    if data["merged"]:
        return "merged"
    if data["state"] == "closed":
        return "closed"
    return "draft" if data["draft"] else "open"


def handle_pull_request(workspace, data, quiet=False):
    """Link a pull request; automations and chat notices run unless ``quiet`` (history sync)."""
    action = data["action"]
    if not quiet and action not in (
        "opened",
        "edited",
        "reopened",
        "closed",
        "synchronize",
        "ready_for_review",
        "converted_to_draft",
    ):
        return
    repository = data["repository"]["full_name"]
    keys = find_keys(data["title"]) + find_keys(data["head"], any_case=True) + find_keys(data["body"])
    keys = list(dict.fromkeys(keys))
    state = pr_state(data)
    user = data["user"]
    became_open = action in ("opened", "reopened", "ready_for_review") and state == "open"
    became_merged = action == "closed" and state == "merged"
    actor = None

    for issue in resolve_issues(workspace.id, keys):
        upsert_link(
            issue,
            "pull_request",
            repository,
            data["number"],
            {
                "title": data["title"][:500],
                "url": data["html_url"],
                "state": state,
                "author_login": user["login"],
                "author_avatar_url": user["avatar_url"],
                "event_at": parse_time(data["updated_at"]),
                "metadata": {"head": data["head"], "base": data["base"]},
            },
        )
        if quiet or not (became_open or became_merged):
            continue

        project_settings = get_project_settings(issue.project_id)
        target = None
        if project_settings is not None:
            if became_merged:
                target = project_settings.pr_merged_state
            elif issue.state is None or issue.state.group not in CLOSED_GROUPS:
                target = project_settings.pr_opened_state
        if target is not None:
            if actor is None:
                actor = user_for(workspace.id, github_id=user["id"]) or get_bot_user()
            change_state(issue, target, actor)

        notify_chat_pull_request.delay(
            str(issue.project_id),
            str(issue.id),
            "merged" if became_merged else "opened",
            {
                "number": data["number"],
                "title": data["title"],
                "url": data["html_url"],
                "repository": repository,
                "author": user["login"],
            },
            uuid.uuid4().hex,
        )


@shared_task
def process_github_event(event, data):
    try:
        workspace = get_workspace()
        if workspace is None:
            logger.warning("conjo_github: workspace %s not found", settings.CONJO_GITHUB_WORKSPACE_SLUG)
            return
        if event == "push":
            handle_push(workspace, data)
        elif event == "create":
            handle_branch(workspace, data)
        elif event == "delete":
            handle_branch(workspace, data, deleted=True)
        elif event == "pull_request":
            handle_pull_request(workspace, data)
    except Exception as e:
        log_exception(e)


# --------------------------------------------------------------------------- #
# History sync (GitHub API): import the last days and recover missed webhooks
# --------------------------------------------------------------------------- #

GITHUB_API = "https://api.github.com"
LAST_SYNC_CACHE_KEY = "conjo_github:last_sync"
MAX_PAGES = 10


def github_pages(path, params=None):
    """Yield the items of a paginated GitHub REST listing (follows the Link header)."""
    import requests

    url = GITHUB_API + path
    headers = {
        "Authorization": f"Bearer {settings.CONJO_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for _ in range(MAX_PAGES):
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        yield from response.json()
        url = response.links.get("next", {}).get("url")
        params = None
        if not url:
            return


def _is_before(value, since):
    moment = parse_datetime(value) if isinstance(value, str) else None
    return moment is not None and moment < since


def _api_commit(commit):
    """A REST commit in the webhook's compact shape."""
    info = commit.get("commit") or {}
    author = info.get("author") or {}
    return {
        "id": commit.get("sha") or "",
        "message": (info.get("message") or "")[:4000],
        "url": commit.get("html_url") or "",
        "timestamp": author.get("date"),
        "author": {
            "name": author.get("name") or "",
            "email": author.get("email") or "",
            "username": (commit.get("author") or {}).get("login") or "",
        },
    }


def sync_repository(workspace, repo, since):
    full_name = repo["full_name"]
    repository = {"full_name": full_name, "html_url": repo.get("html_url") or ""}
    no_sender = {"login": "", "id": None, "avatar_url": ""}

    for pr in github_pages(
        f"/repos/{full_name}/pulls", {"state": "all", "sort": "updated", "direction": "desc", "per_page": 100}
    ):
        if _is_before(pr.get("updated_at"), since):
            break
        data = compact_payload(
            "pull_request", {"action": "synced", "pull_request": pr, "repository": repository, "sender": no_sender}
        )
        handle_pull_request(workspace, data, quiet=True)

    keyed_branches = []
    for branch in github_pages(f"/repos/{full_name}/branches", {"per_page": 100}):
        name = branch.get("name") or ""
        if find_keys(name, any_case=True):
            keyed_branches.append(name)
            handle_branch(workspace, {"repository": repository, "sender": no_sender, "ref": name}, quiet=True)

    default_branch = repo.get("default_branch") or "main"
    for branch in [default_branch, *[b for b in keyed_branches if b != default_branch]]:
        commits = [
            _api_commit(c)
            for c in github_pages(
                f"/repos/{full_name}/commits", {"sha": branch, "since": since.isoformat(), "per_page": 100}
            )
        ]
        link_commits(workspace, full_name, branch, commits, quiet=True)


@shared_task
def sync_github_history(days=2):
    """Import branches, commits and pull requests of the last ``days`` that mention work items.

    Runs hourly with a short window to recover webhooks that never arrived, and on demand
    (Configurações → GitHub) with 90 days to import the history.
    """
    if not settings.CONJO_GITHUB_TOKEN:
        return
    workspace = get_workspace()
    if workspace is None:
        return
    since = timezone.now() - timedelta(days=days)
    repositories = 0
    try:
        for repo in github_pages(
            f"/orgs/{settings.CONJO_GITHUB_ORG}/repos", {"sort": "pushed", "direction": "desc", "per_page": 100}
        ):
            if _is_before(repo.get("pushed_at"), since):
                break
            try:
                sync_repository(workspace, repo, since)
                repositories += 1
            except Exception as e:
                log_exception(e)
        cache.set(
            LAST_SYNC_CACHE_KEY,
            {"at": timezone.now().isoformat(), "days": days, "repositories": repositories},
            None,
        )
    except Exception as e:
        log_exception(e)


def record_last_event(event, data):
    cache.set(
        LAST_EVENT_CACHE_KEY,
        {
            "event": event,
            "repository": (data or {}).get("repository", {}).get("full_name", ""),
            "at": timezone.now().isoformat(),
        },
        None,
    )


@shared_task(bind=True, max_retries=5)
def notify_chat_pull_request(self, project_id, issue_id, kind, pr, txn_id):
    """Post "PR aberto/mergeado" in the project's chat room."""
    try:
        if not chat_is_configured():
            return
        from plane.db.models import Issue, ProjectChatIntegration

        integration = ProjectChatIntegration.objects.filter(project_id=project_id).select_related("workspace").first()
        if integration is None or not integration.enabled or not integration.room_id or not integration.notify_github:
            return
        issue = Issue.all_objects.filter(pk=issue_id).select_related("project").first()
        if issue is None:
            return

        ident = f"{issue.project.identifier}-{issue.sequence_id}"
        link = f"{settings.TASKS_PUBLIC_URL}/{integration.workspace.slug}/browse/{ident}/"
        verb = "mergeou" if kind == "merged" else "abriu"
        pr_label = f"PR #{pr['number']} {pr['title']}"
        html = (
            f"<b>{escape(pr['author'] or 'Alguém')}</b> {verb} o "
            f'<a href="{escape(pr["url"])}">{escape(pr_label)}</a> em <code>{escape(pr["repository"])}</code>'
            f' · <a href="{escape(link)}">{escape(ident)}</a> · {escape(issue.name or "")}'
        )
        body = f"{pr['author'] or 'Alguém'} {verb} o {pr_label} em {pr['repository']} · {ident} · {issue.name or ''}"
        send_html_message(integration.room_id, html, body, txn_id=txn_id)
    except MatrixRetryableError as e:
        if self.request.retries >= self.max_retries:
            log_exception(e)
            return
        raise self.retry(exc=e, countdown=e.retry_after)
    except Exception as e:
        log_exception(e)
