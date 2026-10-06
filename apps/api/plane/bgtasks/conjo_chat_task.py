# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Relay work item activity to the project's Conjo Chat (Matrix) room."""

# Python imports
import logging
import re
from uuid import uuid4

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings
from django.utils.html import escape, strip_tags

# Module imports
from plane.utils.conjo_chat import MatrixRetryableError, is_configured, send_html_message
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")

COMMENT_EXCERPT_LENGTH = 200

KIND_CREATED = "created"
KIND_STATE = "state"
KIND_ASSIGNEE_ADDED = "assignee_added"
KIND_ASSIGNEE_REMOVED = "assignee_removed"
KIND_COMMENT = "comment"

KIND_FLAGS = {
    KIND_CREATED: "notify_issue_created",
    KIND_STATE: "notify_state_changed",
    KIND_ASSIGNEE_ADDED: "notify_assignee_changed",
    KIND_ASSIGNEE_REMOVED: "notify_assignee_changed",
    KIND_COMMENT: "notify_comment_created",
}


def user_name(user, fallback=""):
    if user is None:
        return fallback or "Alguém"
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full_name or user.display_name or fallback or "Alguém"


def comment_excerpt(text):
    text = re.sub(r"\s+", " ", strip_tags(text or "")).strip()
    if len(text) > COMMENT_EXCERPT_LENGTH:
        text = text[: COMMENT_EXCERPT_LENGTH - 1].rstrip() + "…"
    return text


def build_message(event, actor, issue, slug):
    """Return ``(html, body)`` for one event, or ``None`` when it can't be rendered."""
    from plane.db.models import IssueComment, User

    ident = f"{issue.project.identifier}-{issue.sequence_id}"
    link = f"{settings.TASKS_PUBLIC_URL}/{slug}/browse/{ident}/"
    title = issue.name or ""

    h_actor = f"<b>{escape(actor)}</b>"
    h_issue = f'<a href="{escape(link)}">{escape(ident)}</a> · {escape(title)}'
    t_issue = f"{ident} · {title}"

    kind = event.get("kind")
    if kind == KIND_CREATED:
        html = f"{h_actor} criou {h_issue}"
        body = f"{actor} criou {t_issue}"
    elif kind == KIND_STATE:
        old, new = event.get("old"), event.get("new")
        if not new:
            return None
        if old:
            html = f"{h_actor} moveu {h_issue} de <i>{escape(old)}</i> para <i>{escape(new)}</i>"
            body = f"{actor} moveu {t_issue} de {old} para {new}"
        else:
            html = f"{h_actor} moveu {h_issue} para <i>{escape(new)}</i>"
            body = f"{actor} moveu {t_issue} para {new}"
    elif kind in (KIND_ASSIGNEE_ADDED, KIND_ASSIGNEE_REMOVED):
        assignee = User.objects.filter(pk=event.get("user_id")).first() if event.get("user_id") else None
        name = user_name(assignee, fallback=event.get("name") or "")
        if kind == KIND_ASSIGNEE_ADDED:
            html = f"{h_actor} atribuiu {h_issue} a <b>{escape(name)}</b>"
            body = f"{actor} atribuiu {t_issue} a {name}"
        else:
            html = f"{h_actor} removeu <b>{escape(name)}</b> de {h_issue}"
            body = f"{actor} removeu {name} de {t_issue}"
    elif kind == KIND_COMMENT:
        comment = (
            IssueComment.objects.filter(pk=event.get("comment_id")).first() if event.get("comment_id") else None
        )
        if comment is not None:
            text = comment_excerpt(comment.comment_stripped or comment.comment_html)
        else:
            text = comment_excerpt(event.get("text"))
        if not text:
            return None
        html = f"{h_actor} comentou em {h_issue}: “{escape(text)}”"
        body = f"{actor} comentou em {t_issue}: “{text}”"
    else:
        return None

    return html, f"{body}\n{link}"


@shared_task(bind=True, max_retries=5)
def notify_chat_room(self, project_id, issue_id, actor_id, events):
    """Send one message per event to the project's room.

    ``events`` is a JSON-serializable list of dicts with a ``kind`` (see KIND_*)
    and a ``txn_id`` reused across retries so Matrix deduplicates resends.
    """
    from plane.db.models import Issue, ProjectChatIntegration, User

    try:
        if not is_configured() or not events:
            return
        integration = (
            ProjectChatIntegration.objects.filter(project_id=project_id).select_related("workspace").first()
        )
        if integration is None or not integration.enabled or not integration.room_id:
            return

        issue = Issue.all_objects.filter(pk=issue_id).select_related("project").first()
        if issue is None:
            return

        actor = user_name(User.objects.filter(pk=actor_id).first() if actor_id else None)
        slug = integration.workspace.slug

        for event in events:
            flag = KIND_FLAGS.get(event.get("kind"))
            if flag is None or not getattr(integration, flag, False):
                continue
            message = build_message(event, actor, issue, slug)
            if message is None:
                continue
            html, body = message
            send_html_message(integration.room_id, html, body, txn_id=event.get("txn_id"))
    except MatrixRetryableError as e:
        if self.request.retries >= self.max_retries:
            log_exception(e)
            return
        raise self.retry(exc=e, countdown=e.retry_after)
    except Exception as e:
        log_exception(e)


def enqueue_chat_notifications(type, issue_id, actor_id, project_id, activities):
    """Called from the activity pipeline; never raises."""
    try:
        if not issue_id or not project_id or not is_configured():
            return

        from plane.db.models import Issue, ProjectChatIntegration

        if not ProjectChatIntegration.objects.filter(
            project_id=project_id, enabled=True, room_id__isnull=False
        ).exists():
            return

        events = []
        if type == "issue.activity.created":
            # Assignments made while creating are part of the "criou" notice.
            events.append({"kind": KIND_CREATED})
            issue = Issue.all_objects.filter(pk=issue_id).only("created_by_id").first()
            if issue is not None and issue.created_by_id:
                actor_id = issue.created_by_id
        elif type in ("issue.activity.updated", "comment.activity.created"):
            for activity in activities or []:
                if activity.field == "state":
                    events.append({"kind": KIND_STATE, "old": activity.old_value, "new": activity.new_value})
                elif activity.field == "assignees":
                    if activity.new_identifier:
                        events.append(
                            {
                                "kind": KIND_ASSIGNEE_ADDED,
                                "user_id": str(activity.new_identifier),
                                "name": activity.new_value,
                            }
                        )
                    elif activity.old_identifier:
                        events.append(
                            {
                                "kind": KIND_ASSIGNEE_REMOVED,
                                "user_id": str(activity.old_identifier),
                                "name": activity.old_value,
                            }
                        )
                elif activity.field == "comment" and activity.verb == "created":
                    events.append(
                        {
                            "kind": KIND_COMMENT,
                            "comment_id": str(activity.issue_comment_id) if activity.issue_comment_id else None,
                        }
                    )

        if not events:
            return
        for event in events:
            event["txn_id"] = uuid4().hex

        notify_chat_room.delay(
            str(project_id), str(issue_id), str(actor_id) if actor_id else None, events
        )
    except Exception as e:
        log_exception(e)
