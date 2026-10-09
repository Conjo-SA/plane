# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Relay work item activity to the project's Conjo Chat (Matrix) room.

Every notice is a ``m.room.message`` with a plain ``body``, an HTML
``formatted_body`` and a structured ``com.conjosa.tasks.notice`` payload that the
Conjo Element draws as a card (MAN-209). Two kinds of grouping keep the room quiet:

* notices about the same card within ``GROUP_WINDOW`` edit the previous message
  (``m.replace``) and accumulate its ``steps`` instead of posting a new one;
* the same person moving several cards to the same state within ``BATCH_WINDOW``
  seconds produces a single notice listing every card.
"""

# Python imports
import json
import logging
import re
import time
from contextlib import contextmanager
from uuid import uuid4

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.html import escape, strip_tags

# Module imports
from plane.utils.conjo_chat import MatrixError, MatrixRetryableError, edit_notice, is_configured, send_notice
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

# Structured payload read by the Conjo Element (contract v1, see MAN-209).
NOTICE_KEY = "com.conjosa.tasks.notice"
NOTICE_VERSION = 1

# Same card, any actor: edit the last notice while it is younger than this (seconds).
GROUP_WINDOW = 10 * 60
MAX_STEPS = 20
LAST_NOTICE_KEY = "conjo_chat:last_notice:{room_id}:{issue_id}"
CARD_LOCK_KEY = "conjo_chat:lock:{room_id}:{issue_id}"

# Same actor moving several cards to the same state: wait this long and post one notice.
BATCH_WINDOW = 5
BATCH_KEY = "conjo_chat:batch:{project_id}:{actor_id}:{state_id}"
# Long enough to survive a busy Celery queue: the flush must still find the moves.
BATCH_TTL = 60 * 60

CTA_OPEN = "Abrir no Tasks"
CTA_REPLY = "Responder"

# Plane's state groups; the HTML colours the new state by group so the fallback
# matches the card the Element draws.
STATE_GROUP_COLORS = {
    "backlog": "#8b8d98",
    "unstarted": "#3f76ff",
    "started": "#f59e0b",
    "completed": "#16a34a",
    "cancelled": "#dc2626",
    "triage": "#8b5cf6",
}
DEFAULT_STATE_COLOR = "#8b8d98"

# A batch notice lists at most this many cards; the rest becomes a "+N cards" chip.
MAX_BATCH_ISSUES = 30
# Matrix caps events at 64 KiB; stay below it with room for the event envelope.
MAX_CONTENT_BYTES = 60 * 1024

BOT_NAME_SUFFIX = re.compile(r"\s*\(MCP\)\s*$")


def user_name(user, fallback=""):
    if user is None:
        return fallback or "Alguém"
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full_name or user.display_name or fallback or "Alguém"


def actor_payload(user, fallback=""):
    """``{"name", "is_bot"}``; bots (MCP assistant, GitHub automations) drop the "(MCP)" suffix."""
    name = user_name(user, fallback)
    is_bot = bool(getattr(user, "is_bot", False))
    if is_bot:
        name = BOT_NAME_SUFFIX.sub("", name) or name
    return {"name": name, "is_bot": is_bot}


def comment_excerpt(text):
    text = re.sub(r"\s+", " ", strip_tags(text or "")).strip()
    if len(text) > COMMENT_EXCERPT_LENGTH:
        text = text[: COMMENT_EXCERPT_LENGTH - 1].rstrip() + "…"
    return text


def https_url(url):
    """Only ``https://`` links go into notices."""
    return url if isinstance(url, str) and url.lower().startswith("https://") else None


def now_iso():
    return timezone.now().isoformat()


def issue_payload(issue, slug):
    key = f"{issue.project.identifier}-{issue.sequence_id}"
    return {
        "key": key,
        "title": issue.name or "",
        "url": https_url(f"{settings.TASKS_PUBLIC_URL}/{slug}/browse/{key}/"),
    }


def state_payload(name, group):
    return {"name": name, "group": group or None} if name else None


def state_html(state):
    color = STATE_GROUP_COLORS.get(state.get("group"), DEFAULT_STATE_COLOR)
    return f'<font data-mx-color="{color}">● {escape(state["name"])}</font>'


def card_cta(issue_ref, label=CTA_OPEN):
    return {"label": label, "url": issue_ref["url"]} if issue_ref.get("url") else None


def fragment(kind, actor, text, html, issue_ref=None, **extra):
    """One event, ready to become (or be merged into) a notice.

    ``text`` is the plain step line and ``html`` its rich version (only the newest
    step is shown rich; older ones are listed as plain text).
    """
    data = {
        "kind": kind,
        "actor": actor,
        "from": None,
        "to": None,
        "quote": None,
        "chips": [],
        "cta": card_cta(issue_ref) if issue_ref else None,
        "at": now_iso(),
        "text": text,
        "html": html,
        "mention_room": False,
        "msgtype": "m.notice",
    }
    data.update(extra)
    return data


# --------------------------------------------------------------------------- #
# Events → fragments
# --------------------------------------------------------------------------- #

PRIORITY_LABELS = {"urgent": "Urgente", "high": "Alta", "medium": "Média", "low": "Baixa"}


def build_intake_fragment(issue, intake_issue, issue_ref):
    """Objective notice for a request that came from the public form (Entrada), tagging everyone."""
    from plane.db.models import FileAsset

    requester = (intake_issue.extra or {}).get("requester_name") or ""
    email = intake_issue.source_email or ""
    client = f"{requester} ({email})" if requester and email else requester or email or "não informado"
    chips = [f"Cliente: {client}"]
    priority = PRIORITY_LABELS.get(issue.priority)
    if priority:
        chips.append(f"Prioridade: {priority}")
    labels = ", ".join(issue.labels.values_list("name", flat=True))
    if labels:
        chips.append(f"Etiqueta: {labels}")
    attachments = FileAsset.objects.filter(
        issue_id=issue.id, entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT, is_uploaded=True
    ).count()
    if attachments:
        chips.append(f"{attachments} anexo{'s' if attachments > 1 else ''}")

    return fragment(
        "intake",
        {"name": requester or email or "Cliente", "is_bot": False},
        "Nova solicitação na Entrada",
        "<b>Nova solicitação na Entrada</b>",
        issue_ref,
        chips=chips,
        quote=comment_excerpt(issue.description_html) or None,
        mention_room=True,
        # m.notice is silenced by the default push rules (.m.rule.suppress_notices runs before
        # .m.rule.is_room_mention), so the @room request stays a regular message.
        msgtype="m.text",
    )


def _state_groups(project_id, *state_ids):
    from plane.db.models import State

    ids = [state_id for state_id in state_ids if state_id]
    if not ids:
        return {}
    return {
        str(pk): group
        for pk, group in State.all_state_objects.filter(project_id=project_id, pk__in=ids).values_list("pk", "group")
    }


def build_fragment(event, actor, issue, slug):
    """Return the fragment for one activity event, or ``None`` when it can't be rendered.

    ``actor`` is ``{"name", "is_bot"}``.
    """
    from plane.db.models import IntakeIssue, IssueComment, User
    from plane.db.models.intake import SourceType

    issue_ref = issue_payload(issue, slug)
    name = actor["name"]
    h_actor = f"<b>{escape(name)}</b>"
    at = event.get("at") or now_iso()

    kind = event.get("kind")
    if kind == KIND_CREATED:
        intake_issue = IntakeIssue.objects.filter(issue_id=issue.id, source=SourceType.PORTAL).first()
        if intake_issue is not None:
            return build_intake_fragment(issue, intake_issue, issue_ref) | {"at": at}
        return fragment("created", actor, f"{name} criou o card", f"{h_actor} criou o card", issue_ref, at=at)

    if kind == KIND_STATE:
        old, new = event.get("old"), event.get("new")
        if not new:
            return None
        groups = _state_groups(issue.project_id, event.get("old_id"), event.get("new_id"))
        from_state = state_payload(old, groups.get(str(event.get("old_id"))))
        to_state = state_payload(new, groups.get(str(event.get("new_id"))))
        if old:
            text = f"{name} moveu de {old} para {new}"
            html = f"{h_actor} moveu de <i>{escape(old)}</i> para {state_html(to_state)}"
        else:
            text = f"{name} moveu para {new}"
            html = f"{h_actor} moveu para {state_html(to_state)}"
        return fragment("moved", actor, text, html, issue_ref, at=at, **{"from": from_state, "to": to_state})

    if kind in (KIND_ASSIGNEE_ADDED, KIND_ASSIGNEE_REMOVED):
        assignee = User.objects.filter(pk=event.get("user_id")).first() if event.get("user_id") else None
        assignee_name = actor_payload(assignee, fallback=event.get("name") or "")["name"]
        if kind == KIND_ASSIGNEE_ADDED:
            text = f"{name} atribuiu a {assignee_name}"
            html = f"{h_actor} atribuiu a <b>{escape(assignee_name)}</b>"
            return fragment("assigned", actor, text, html, issue_ref, at=at)
        text = f"{name} removeu {assignee_name}"
        html = f"{h_actor} removeu <b>{escape(assignee_name)}</b>"
        return fragment("unassigned", actor, text, html, issue_ref, at=at)

    if kind == KIND_COMMENT:
        comment = IssueComment.objects.filter(pk=event.get("comment_id")).first() if event.get("comment_id") else None
        if comment is not None:
            text = comment_excerpt(comment.comment_stripped or comment.comment_html)
        else:
            text = comment_excerpt(event.get("text"))
        if not text:
            return None
        return fragment(
            "commented",
            actor,
            f"{name} comentou",
            f"{h_actor} comentou",
            issue_ref,
            at=at,
            quote=text,
            cta=card_cta(issue_ref, CTA_REPLY),
        )

    return None


PR_VERBS = {"opened": "abriu", "merged": "mergeou", "closed": "fechou sem merge"}


def pull_request_fragment(kind, pr):
    """``kind`` is opened, merged or closed; ``pr`` the compact pull request of the webhook."""
    login = pr.get("author") or "Alguém"
    actor = {"name": login, "is_bot": login.endswith("[bot]")}
    verb = PR_VERBS.get(kind, PR_VERBS["opened"])
    number = pr.get("number")
    title = pr.get("title") or ""
    repository = pr.get("repository") or ""
    url = https_url(pr.get("url"))
    pr_label = f"PR #{number}"
    h_pr = f'<a href="{escape(url)}">{escape(pr_label)}</a>' if url else escape(pr_label)
    text = f"{login} {verb} o {pr_label} {title}".rstrip()
    html = f"<b>{escape(login)}</b> {escape(verb)} o {h_pr} {escape(title)}".rstrip()
    if repository:
        text += f" em {repository}"
        html += f" em <code>{escape(repository)}</code>"
    return fragment(
        f"pr_{kind}",
        actor,
        text,
        html,
        chips=[repository] if repository else [],
        cta={"label": f"Ver {pr_label}", "url": url} if url else None,
    )


# --------------------------------------------------------------------------- #
# Notice (contract) and Matrix content
# --------------------------------------------------------------------------- #


def _step(frag):
    return {"text": frag["text"], "at": frag["at"], "kind": frag["kind"]}


def new_notice(frag, issues):
    return {
        "v": NOTICE_VERSION,
        "kind": frag["kind"],
        "issues": issues,
        "actor": frag["actor"],
        "from": frag["from"],
        "to": frag["to"],
        "quote": frag["quote"],
        "chips": list(dict.fromkeys(frag["chips"])),
        "steps": [_step(frag)],
        "cta": frag["cta"] or (card_cta(issues[0]) if len(issues) == 1 else None),
        "at": frag["at"],
    }


def merge_notice(notice, frag, issue_ref):
    """Fold a newer event of the same card into its notice (the card shows the latest state)."""
    merged = dict(notice)
    merged["kind"] = frag["kind"]
    merged["issues"] = [issue_ref]
    merged["actor"] = frag["actor"]
    if frag["to"]:
        # A → B then B → C reads as A → C.
        merged["from"] = notice.get("from") if notice.get("to") else frag["from"]
        merged["to"] = frag["to"]
    merged["quote"] = frag["quote"] or notice.get("quote")
    merged["chips"] = list(dict.fromkeys([*notice.get("chips", []), *frag["chips"]]))
    merged["steps"] = [*notice.get("steps", []), _step(frag)]
    # "Ver PR #N" / "Responder" are more useful than the generic link, so a plain move keeps them.
    old_cta = notice.get("cta")
    if frag["cta"] and (frag["cta"]["label"] != CTA_OPEN or not old_cta):
        merged["cta"] = frag["cta"]
    else:
        merged["cta"] = old_cta or frag["cta"] or card_cta(issue_ref)
    merged["at"] = frag["at"]
    return merged


def _issue_html(issue):
    key = f"<b>{escape(issue['key'])}</b>"
    if issue.get("url"):
        key = f'<a href="{escape(issue["url"])}">{key}</a>'
    return f"{key} {escape(issue['title'])}".rstrip()


def _chip_html(chip):
    label, sep, value = chip.partition(": ")
    if sep and value:
        return f"<b>{escape(label)}:</b> {escape(value)}"
    return escape(chip)


def render(notice, latest_html, mention_room=False):
    """``(html, body)``: line 1 the card(s), then the steps (newest rich), chips and the quote."""
    issues = notice["issues"]
    steps = notice["steps"]
    html_lines = ["<br>".join(_issue_html(issue) for issue in issues)]
    text_lines = [f"{issue['key']} {issue['title']}".rstrip() for issue in issues]
    html_lines += [escape(step["text"]) for step in steps[:-1]] + [latest_html]
    text_lines += [step["text"] for step in steps]
    if notice.get("chips"):
        html_lines.append(" · ".join(_chip_html(chip) for chip in notice["chips"]))
        text_lines.append(" · ".join(notice["chips"]))
    html = "<br>".join(html_lines)
    if notice.get("quote"):
        html += f"<blockquote>{escape(notice['quote'])}</blockquote>"
        text_lines.append(f"“{notice['quote']}”")
    links = []
    if len(issues) == 1 and issues[0].get("url"):
        links.append(issues[0]["url"])
    cta_url = (notice.get("cta") or {}).get("url")
    if cta_url and cta_url not in links:
        links.append(cta_url)
    text_lines += links
    if mention_room:
        html += "<br>@room"
        text_lines.append("@room")
    return html, "\n".join(text_lines)


def build_content(notice, latest_html, mention_room=False, msgtype="m.notice"):
    html, body = render(notice, latest_html, mention_room)
    content = {
        "msgtype": msgtype,
        "body": body,
        "format": "org.matrix.custom.html",
        "formatted_body": html,
        NOTICE_KEY: notice,
    }
    # Intentional mentions (MSC3952): only the Entrada request tags the room (the bot has the
    # room's "notifications.room" power); every other notice explicitly mentions no one.
    content["m.mentions"] = {"room": True} if mention_room else {}
    return fit_content(content, notice, latest_html, mention_room, msgtype)


def content_size(content):
    return len(json.dumps(content, ensure_ascii=False).encode("utf-8"))


def fit_content(content, notice, latest_html, mention_room, msgtype):
    """Keep the event under ``MAX_CONTENT_BYTES`` dropping the oldest steps, then the quote."""
    if content_size(content) <= MAX_CONTENT_BYTES:
        return content
    notice = dict(notice)
    while content_size(content) > MAX_CONTENT_BYTES and (len(notice["steps"]) > 1 or notice.get("quote")):
        if len(notice["steps"]) > 1:
            notice["steps"] = notice["steps"][1:]
        else:
            notice["quote"] = None
        html, body = render(notice, latest_html, mention_room)
        content = {**content, "body": body, "formatted_body": html, NOTICE_KEY: notice}
    logger.warning("conjo_chat: notice trimmed to %s bytes", content_size(content))
    return content


def is_too_large(error):
    return error.status_code == 413 or error.errcode == "M_TOO_LARGE"


# --------------------------------------------------------------------------- #
# Posting: edit the card's last notice within the window, otherwise a new message
# --------------------------------------------------------------------------- #


@contextmanager
def _card_lock(room_id, issue_id):
    """Serialize notices of one card across workers; runs unlocked if Redis can't lock."""
    lock = None
    try:
        from plane.settings.redis import redis_instance

        lock = redis_instance().lock(
            CARD_LOCK_KEY.format(room_id=room_id, issue_id=issue_id), timeout=60, blocking_timeout=20
        )
        if not lock.acquire():
            lock = None
    except Exception as e:  # noqa: BLE001 - grouping is best effort, the notice is not
        logger.warning("conjo_chat: card lock unavailable: %s", e)
        lock = None
    try:
        yield
    finally:
        if lock is not None:
            try:
                lock.release()
            except Exception:  # noqa: BLE001 - expired lock
                pass


def post_card_notice(room_id, issue_id, issue_ref, fragments, txn_id):
    """Send ``fragments`` (oldest first) about one card, editing its recent notice when there is one."""
    if not fragments:
        return None
    key = LAST_NOTICE_KEY.format(room_id=room_id, issue_id=issue_id)
    latest = fragments[-1]
    with _card_lock(room_id, issue_id):
        last = cache.get(key)
        if (
            last
            and time.time() - last.get("ts", 0) <= GROUP_WINDOW
            and len(last["notice"].get("steps", [])) + len(fragments) <= MAX_STEPS
        ):
            notice = last["notice"]
            for frag in fragments:
                notice = merge_notice(notice, frag, issue_ref)
            content = build_content(notice, latest["html"], last.get("mention_room", False), last.get("msgtype"))
            try:
                # Own transaction per (event, edited message): a retry that falls on the "new
                # message" path must not be deduplicated against an edit.
                edit_notice(room_id, last["event_id"], content, txn_id=f"{txn_id}-edit-{last['event_id']}")
            except MatrixRetryableError:
                raise
            except MatrixError as e:
                # Never lose a notice: post it as a new message instead.
                logger.warning("conjo_chat: could not edit %s (%s), sending a new notice", last["event_id"], e)
                txn_id = f"{txn_id}-new"
            else:
                cache.set(key, {**last, "ts": time.time(), "notice": notice}, GROUP_WINDOW)
                return last["event_id"]

        notice = new_notice(fragments[0], [issue_ref])
        for frag in fragments[1:]:
            notice = merge_notice(notice, frag, issue_ref)
        mention_room = any(frag["mention_room"] for frag in fragments)
        msgtype = "m.text" if any(frag["msgtype"] == "m.text" for frag in fragments) else "m.notice"
        event_id = send_notice(room_id, build_content(notice, latest["html"], mention_room, msgtype), txn_id=txn_id)
        if event_id:
            cache.set(
                key,
                {
                    "event_id": event_id,
                    "ts": time.time(),
                    "notice": notice,
                    "mention_room": mention_room,
                    "msgtype": msgtype,
                },
                GROUP_WINDOW,
            )
        return event_id


def batch_move_fragment(actor, issues, events, project_id):
    """One "moved" fragment for several cards moved by the same person to the same state."""
    first = events[0]
    groups = _state_groups(project_id, first.get("new_id"))
    to_state = state_payload(first.get("new"), groups.get(str(first.get("new_id"))))
    olds = {event.get("old") for event in events}
    old = olds.pop() if len(olds) == 1 else None
    from_state = None
    if old:
        old_groups = _state_groups(project_id, first.get("old_id"))
        from_state = state_payload(old, old_groups.get(str(first.get("old_id"))))
    name = actor["name"]
    count = f"{len(issues)} cards"
    if old:
        text = f"{name} moveu {count} de {old} para {to_state['name']}"
        html = f"<b>{escape(name)}</b> moveu {count} de <i>{escape(old)}</i> para {state_html(to_state)}"
    else:
        text = f"{name} moveu {count} para {to_state['name']}"
        html = f"<b>{escape(name)}</b> moveu {count} para {state_html(to_state)}"
    frag = fragment("moved", actor, text, html, at=first.get("at") or now_iso())
    frag.update({"from": from_state, "to": to_state})
    return frag


@shared_task(bind=True, max_retries=5)
def notify_chat_room(self, project_id, issue_id, actor_id, events, batch_issue_ids=None):
    """Post (or fold into the card's recent notice) the events of one work item.

    ``events`` is a JSON-serializable list of dicts with a ``kind`` (see KIND_*)
    and a ``txn_id`` reused across retries so Matrix deduplicates resends.
    ``batch_issue_ids`` (state changes only) lists every card of a batch move.
    """
    from plane.db.models import Issue, ProjectChatIntegration, User

    try:
        if not is_configured() or not events:
            return
        integration = ProjectChatIntegration.objects.filter(project_id=project_id).select_related("workspace").first()
        if integration is None or not integration.enabled or not integration.room_id:
            return

        issue = Issue.all_objects.filter(pk=issue_id).select_related("project").first()
        if issue is None:
            return

        actor = actor_payload(User.objects.filter(pk=actor_id).first() if actor_id else None)
        slug = integration.workspace.slug
        events = [event for event in events if getattr(integration, KIND_FLAGS.get(event.get("kind"), ""), False)]
        if not events:
            return

        if batch_issue_ids and len(batch_issue_ids) > 1:
            # Defence in depth: a batch only ever holds cards of the room's own project.
            issues = list(
                Issue.all_objects.filter(pk__in=batch_issue_ids, project_id=project_id).select_related("project")
            )
            issues.sort(key=lambda item: batch_issue_ids.index(str(item.pk)))
            if len(issues) > 1:
                refs = [issue_payload(item, slug) for item in issues]
                frag = batch_move_fragment(actor, refs, events, project_id)
                hidden = len(refs) - MAX_BATCH_ISSUES
                if hidden > 0:
                    frag["chips"] = [f"+{hidden} cards"]
                notice = new_notice(frag, refs[:MAX_BATCH_ISSUES])
                send_notice(integration.room_id, build_content(notice, frag["html"]), txn_id=events[0].get("txn_id"))
                return
            # Only one card of the batch still exists: a regular notice for it.
            issue = issues[0] if issues else issue
            position = batch_issue_ids.index(str(issue.pk)) if str(issue.pk) in batch_issue_ids else 0
            events = events[position : position + 1] or events[:1]

        fragments = [frag for frag in (build_fragment(event, actor, issue, slug) for event in events) if frag]
        if not fragments:
            return
        post_card_notice(
            integration.room_id, str(issue.id), issue_payload(issue, slug), fragments, events[0].get("txn_id")
        )
    except MatrixRetryableError as e:
        if self.request.retries >= self.max_retries:
            log_exception(e)
            return
        raise self.retry(exc=e, countdown=e.retry_after)
    except MatrixError as e:
        if is_too_large(e):
            logger.warning("conjo_chat: notice refused as too large for issue %s: %s", issue_id, e)
            return
        log_exception(e)
    except Exception as e:
        log_exception(e)


# --------------------------------------------------------------------------- #
# Batch moves
# --------------------------------------------------------------------------- #


def queue_batched_move(project_id, issue_id, actor_id, event):
    """Hold a state change for ``BATCH_WINDOW`` seconds so a multi-card move posts once.

    Every queued move schedules its own flush; the first flush takes every move of
    the group (atomically), later ones find the list empty. Falls back to posting
    right away when Redis is unavailable.
    """
    key = BATCH_KEY.format(project_id=project_id, actor_id=actor_id, state_id=event["new_id"])
    try:
        from plane.settings.redis import redis_instance

        ri = redis_instance()
        pipe = ri.pipeline(transaction=True)
        pipe.rpush(key, json.dumps({"issue_id": str(issue_id), "event": event}))
        pipe.expire(key, BATCH_TTL)
        pipe.execute()
    except Exception as e:  # noqa: BLE001 - never lose the notice
        logger.warning("conjo_chat: batch unavailable, posting right away: %s", e)
        notify_chat_room.delay(str(project_id), str(issue_id), str(actor_id), [event])
        return
    flush_chat_batch.apply_async(args=[key, str(project_id), str(actor_id)], countdown=BATCH_WINDOW)


@shared_task
def flush_chat_batch(key, project_id, actor_id):
    try:
        from plane.settings.redis import redis_instance

        pipe = redis_instance().pipeline(transaction=True)
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        raw_items, _ = pipe.execute()
        if not raw_items:
            return
        items = {}
        for raw in raw_items:
            item = json.loads(raw)
            items.setdefault(item["issue_id"], item)
        items = list(items.values())
        events = [item["event"] for item in items]
        notify_chat_room.delay(
            project_id,
            items[0]["issue_id"],
            actor_id,
            events,
            batch_issue_ids=[item["issue_id"] for item in items] if len(items) > 1 else None,
        )
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
                    events.append(
                        {
                            "kind": KIND_STATE,
                            "old": activity.old_value,
                            "new": activity.new_value,
                            "old_id": str(activity.old_identifier) if activity.old_identifier else None,
                            "new_id": str(activity.new_identifier) if activity.new_identifier else None,
                        }
                    )
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
        at = now_iso()
        for event in events:
            event["txn_id"] = uuid4().hex
            event["at"] = at

        actor = str(actor_id) if actor_id else None
        direct = []
        for event in events:
            if event["kind"] == KIND_STATE and event.get("new_id") and actor:
                queue_batched_move(str(project_id), str(issue_id), actor, event)
            else:
                direct.append(event)
        if direct:
            notify_chat_room.delay(str(project_id), str(issue_id), actor, direct)
    except Exception as e:
        log_exception(e)
