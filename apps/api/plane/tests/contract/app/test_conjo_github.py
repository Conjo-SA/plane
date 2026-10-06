# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GitHub integration: webhook → development links, smart commits and PR automations."""

import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.core.cache import cache
from rest_framework import status

from plane.bgtasks import conjo_github_task
from plane.db.models import (
    Issue,
    IssueComment,
    IssueDevelopmentLink,
    Project,
    ProjectGitHubSettings,
    ProjectMember,
    State,
)

SECRET = "test-secret"
WEBHOOK_URL = "/api/conjo/github/webhook/"


@pytest.fixture(autouse=True)
def github_settings(settings, workspace):
    settings.CONJO_GITHUB_WEBHOOK_SECRET = SECRET
    settings.CONJO_GITHUB_WORKSPACE_SLUG = workspace.slug
    cache.clear()


@pytest.fixture(autouse=True)
def sync_tasks():
    """Run the webhook processing inline and record side-effect tasks instead of queueing them."""
    with (
        mock.patch.object(
            conjo_github_task.process_github_event, "delay", side_effect=conjo_github_task.process_github_event
        ),
        mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as activity,
        mock.patch.object(conjo_github_task.notify_chat_pull_request, "delay") as chat,
    ):
        yield {"activity": activity, "chat": chat}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def states(project):
    def make(name, group, seq, default=False):
        return State.objects.create(
            name=name, group=group, sequence=seq, project=project, workspace=project.workspace, default=default
        )

    return {
        "todo": make("A fazer", "unstarted", 1, default=True),
        "doing": make("Em andamento", "started", 2),
        "review": make("Em revisão", "started", 3),
        "done": make("Concluído", "completed", 4),
    }


@pytest.fixture
def issue(project, states):
    return Issue.objects.create(
        name="Corrigir login", project=project, workspace=project.workspace, state=states["todo"]
    )


def send(api_client, event, payload, secret=SECRET, delivery=None):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"HTTP_X_GITHUB_EVENT": event, "HTTP_X_HUB_SIGNATURE_256": signature}
    if delivery:
        headers["HTTP_X_GITHUB_DELIVERY"] = delivery
    return api_client.post(WEBHOOK_URL, data=body, content_type="application/json", **headers)


REPO = {"full_name": "Conjo-SA/app", "html_url": "https://github.com/Conjo-SA/app"}
SENDER = {"login": "dev", "id": 1, "avatar_url": ""}


def push_payload(message, email, sha="a" * 40, ref="refs/heads/man-1-corrigir-login"):
    return {
        "ref": ref,
        "deleted": False,
        "repository": REPO,
        "sender": SENDER,
        "commits": [
            {
                "id": sha,
                "message": message,
                "url": f"https://github.com/Conjo-SA/app/commit/{sha}",
                "timestamp": "2026-10-06T12:00:00Z",
                "author": {"name": "Dev", "email": email, "username": "dev"},
            }
        ],
    }


def pr_payload(action, number=7, merged=False, state="open", draft=False, title="MAN-1 corrige login"):
    return {
        "action": action,
        "repository": REPO,
        "sender": SENDER,
        "pull_request": {
            "number": number,
            "title": title,
            "body": "",
            "html_url": f"https://github.com/Conjo-SA/app/pull/{number}",
            "state": state,
            "merged": merged,
            "draft": draft,
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            "updated_at": "2026-10-06T12:00:00Z",
            "user": {"login": "outsider", "id": 999, "avatar_url": ""},
        },
    }


@pytest.mark.contract
class TestGitHubWebhook:
    def test_rejects_bad_signature(self, api_client, issue):
        response = send(api_client, "push", push_payload("MAN-1 x", "a@b.c"), secret="wrong")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not IssueDevelopmentLink.objects.exists()

    def test_disabled_without_secret(self, api_client, settings, issue):
        settings.CONJO_GITHUB_WEBHOOK_SECRET = ""
        response = send(api_client, "ping", {"zen": "x"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_ping(self, api_client):
        response = send(api_client, "ping", {"zen": "x", "repository": REPO})
        assert response.status_code == status.HTTP_200_OK

    def test_push_links_branch_and_commit(self, api_client, issue, create_user):
        response = send(api_client, "push", push_payload("feat(MAN-1): corrige login", create_user.email))
        assert response.status_code == status.HTTP_202_ACCEPTED

        kinds = set(IssueDevelopmentLink.objects.filter(issue=issue).values_list("kind", flat=True))
        assert kinds == {"branch", "commit"}
        commit = IssueDevelopmentLink.objects.get(issue=issue, kind="commit")
        assert commit.title == "feat(MAN-1): corrige login"
        assert commit.metadata["branch"] == "man-1-corrigir-login"

    def test_unknown_project_is_ignored(self, api_client, issue, create_user):
        send(api_client, "push", push_payload("XYZ-1 e utf-8", create_user.email, ref="refs/heads/main"))
        assert not IssueDevelopmentLink.objects.exists()

    def test_smart_commit_comment_and_transition(self, api_client, issue, states, create_user, sync_tasks):
        message = "MAN-1 #comment ajustei o login #done"
        send(api_client, "push", push_payload(message, create_user.email, ref="refs/heads/main"))

        issue.refresh_from_db()
        assert issue.state_id == states["done"].id
        comment = IssueComment.objects.get(issue=issue)
        assert comment.actor_id == create_user.id
        assert comment.comment_stripped.startswith("ajustei o login")
        assert ">aaaaaaa</a> em Conjo-SA/app" in comment.comment_html
        assert sync_tasks["activity"].call_count == 2  # comment + state change

        # The same commit pushed again (e.g. to another branch) runs nothing twice.
        send(api_client, "push", push_payload(message, create_user.email, ref="refs/heads/release"))
        assert IssueComment.objects.filter(issue=issue).count() == 1

    def test_smart_commit_needs_known_author(self, api_client, issue, states):
        send(api_client, "push", push_payload("MAN-1 #done", "stranger@example.com", ref="refs/heads/main"))
        issue.refresh_from_db()
        assert issue.state_id == states["todo"].id
        assert IssueDevelopmentLink.objects.filter(issue=issue, kind="commit").exists()

    def test_smart_commits_can_be_disabled(self, api_client, project, issue, states, create_user):
        ProjectGitHubSettings.objects.create(project=project, smart_commits=False)
        send(api_client, "push", push_payload("MAN-1 #done", create_user.email, ref="refs/heads/main"))
        issue.refresh_from_db()
        assert issue.state_id == states["todo"].id

    def test_branch_created_and_deleted(self, api_client, issue):
        send(api_client, "create", {"ref": "man-1-tela", "ref_type": "branch", "repository": REPO, "sender": SENDER})
        link = IssueDevelopmentLink.objects.get(issue=issue, kind="branch")
        assert link.url == "https://github.com/Conjo-SA/app/tree/man-1-tela"
        send(api_client, "delete", {"ref": "man-1-tela", "ref_type": "branch", "repository": REPO, "sender": SENDER})
        link.refresh_from_db()
        assert link.state == "deleted"

    def test_pull_request_automations(self, api_client, project, issue, states, sync_tasks):
        ProjectGitHubSettings.objects.create(
            project=project, pr_opened_state=states["review"], pr_merged_state=states["done"]
        )
        send(api_client, "pull_request", pr_payload("opened"))
        issue.refresh_from_db()
        assert issue.state_id == states["review"].id
        link = IssueDevelopmentLink.objects.get(issue=issue, kind="pull_request")
        assert link.state == "open" and link.external_id == "7"
        assert sync_tasks["chat"].call_count == 1

        send(api_client, "pull_request", pr_payload("closed", merged=True, state="closed"))
        issue.refresh_from_db()
        link.refresh_from_db()
        assert issue.state_id == states["done"].id
        assert link.state == "merged"
        assert sync_tasks["chat"].call_count == 2
        # The author has no Tasks account: the "GitHub" bot is the actor.
        actor_id = sync_tasks["activity"].call_args.kwargs["actor_id"]
        from plane.db.models import User

        assert User.objects.get(pk=actor_id).username == conjo_github_task.BOT_USERNAME

    def test_draft_pull_request_does_not_move(self, api_client, project, issue, states):
        ProjectGitHubSettings.objects.create(project=project, pr_opened_state=states["review"])
        send(api_client, "pull_request", pr_payload("opened", draft=True))
        issue.refresh_from_db()
        assert issue.state_id == states["todo"].id
        assert IssueDevelopmentLink.objects.get(issue=issue, kind="pull_request").state == "draft"

    def test_duplicate_delivery_is_processed_once(self, api_client, issue, create_user):
        payload = push_payload("MAN-1 #comment oi", create_user.email, ref="refs/heads/main")
        send(api_client, "push", payload, delivery="d-1")
        IssueDevelopmentLink.objects.all().delete()
        response = send(api_client, "push", payload, delivery="d-1")
        assert response.json().get("duplicate") is True


@pytest.mark.contract
class TestDevelopmentEndpoints:
    def test_issue_development_panel(self, session_client, workspace, project, issue, create_user):
        conjo_github_task.process_github_event(
            "pull_request", conjo_github_task.compact_payload("pull_request", pr_payload("opened"))
        )
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/development/"
        response = session_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["pull_requests"]) == 1
        assert data["branch_name"] == "man-1-corrigir-login"
        assert data["github_configured"] is True

    def test_project_settings(self, session_client, workspace, project, states):
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/github-integration/"
        response = session_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["smart_commits"] is True
        assert response.json()["webhook_url"].endswith("/api/conjo/github/webhook/")

        response = session_client.patch(url, {"pr_merged_state": str(states["done"].id)}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["pr_merged_state"] == str(states["done"].id)
