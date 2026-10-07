# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared shaping helpers for the intake portal.

The team facing API and the public portal API both expose the hourly estimate,
so the contract lives here to keep the two surfaces from drifting apart.
"""

import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from plane.db.models.intake import IntakePortalBudgetStatus

MAX_ESTIMATED_HOURS = Decimal("99999.99")
MAX_BUDGET_NOTE_LENGTH = 2000


def _actor_name(user):
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.display_name or user.email


def serialize_budget_event(event, for_client=False):
    """One step of an estimate's timeline. The client sees "Equipe" instead of team members' names."""
    if event.actor_id and not for_client:
        actor = _actor_name(event.actor)
    elif event.actor_email:
        actor = event.actor_email
    else:
        actor = "Equipe"
    return {
        "id": str(event.id),
        "kind": event.kind,
        "hours": float(event.hours),
        "note": event.note,
        "previous_hours": float(event.previous_hours) if event.previous_hours is not None else None,
        "previous_note": event.previous_note,
        "note_changed": event.kind == "revised" and event.note != event.previous_note,
        "actor": actor,
        "reason": event.reason,
        "occurred_at": event.occurred_at,
    }


def serialize_portal_budget(budget, for_client=False):
    """Return the public shape of an hourly estimate (with its timeline), or None."""
    if budget is None:
        return None

    events = list(budget.events.all())
    return {
        "id": str(budget.id),
        "estimated_hours": float(budget.estimated_hours),
        "note": budget.note,
        "status": budget.status,
        "is_approved": budget.status == IntakePortalBudgetStatus.APPROVED,
        "is_rejected": budget.status == IntakePortalBudgetStatus.REJECTED,
        "requested_at": budget.requested_at,
        "approved_at": budget.approved_at,
        "approved_by_email": budget.approved_by_email,
        "rejected_at": budget.rejected_at,
        "rejected_by_email": budget.rejected_by_email,
        "rejection_reason": budget.rejection_reason,
        "events": [serialize_budget_event(event, for_client) for event in events],
        "revision_count": sum(1 for event in events if event.kind == "revised"),
        # only a pending estimate can be edited; an approved one is final
        "can_edit": budget.status == IntakePortalBudgetStatus.PENDING,
    }


def record_budget_event(budget, kind, actor_id=None, actor_email="", previous=None, reason=""):
    from plane.db.models import IntakePortalBudgetEvent

    return IntakePortalBudgetEvent.objects.create(
        budget=budget,
        project_id=budget.project_id,
        workspace_id=budget.workspace_id,
        kind=kind,
        hours=budget.estimated_hours,
        note=budget.note or "",
        previous_hours=previous[0] if previous else None,
        previous_note=previous[1] if previous else "",
        actor_id=actor_id,
        actor_email=actor_email or "",
        reason=reason or "",
        occurred_at=timezone.now(),
    )


def parse_estimated_hours(raw_value):
    """Validate the submitted hours. Returns (hours, error)."""
    if raw_value is None or raw_value == "":
        return None, "Informe as horas estimadas."

    try:
        hours = Decimal(str(raw_value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None, "Informe um número válido de horas."

    if hours <= 0:
        return None, "As horas estimadas devem ser maiores que zero."
    if hours > MAX_ESTIMATED_HOURS:
        return None, f"As horas estimadas devem ser no máximo {MAX_ESTIMATED_HOURS}."

    return hours, None


def issue_budgets(issue_id):
    """Every estimate of a ticket, oldest first."""
    from plane.db.models import IntakePortalBudget

    return list(
        IntakePortalBudget.objects.filter(issue_id=issue_id).order_by("created_at").prefetch_related("events__actor")
    )


def current_budget(budgets):
    """The estimate the screens highlight: the pending one, else the latest."""
    pending = [b for b in budgets if b.status == IntakePortalBudgetStatus.PENDING]
    if pending:
        return pending[-1]
    return budgets[-1] if budgets else None


def approved_hours(budgets):
    return sum((b.estimated_hours for b in budgets if b.status == IntakePortalBudgetStatus.APPROVED), Decimal("0"))


def serialize_budget_context(issue_id, for_client=False):
    """``budget`` (the highlighted one), ``budgets`` (history, oldest first) and the approved total."""
    budgets = issue_budgets(issue_id)
    return {
        "budget": serialize_portal_budget(current_budget(budgets), for_client),
        "budgets": [serialize_portal_budget(b, for_client) for b in budgets],
        "approved_hours": float(approved_hours(budgets)),
    }


def request_portal_budget(intake_issue, raw_hours, raw_note, created_by_id=None, actor_id=None):
    """Send an hourly estimate for a portal ticket and e-mail the requester.

    Shared by the team screen and the MCP so both follow the same rules: the hours are validated, a
    pending estimate is repriced in place, and otherwise a new estimate is created (after a rejection,
    or as an additional estimate after an approval). Approved estimates are never touched. Every send and
    every edit goes to the estimate's timeline (an edit keeps the previous hours and note). ``actor_id``:
    who sent it (defaults to ``created_by_id``). Returns (budget, error).
    """
    from plane.bgtasks.intake_portal_task import send_portal_budget_request
    from plane.db.models import IntakePortalBudget

    hours, hours_error = parse_estimated_hours(raw_hours)
    if hours_error:
        return None, hours_error

    note = (raw_note or "").strip()[:MAX_BUDGET_NOTE_LENGTH]

    with transaction.atomic():
        budget = (
            IntakePortalBudget.objects.select_for_update()
            .filter(issue_id=intake_issue.issue_id, status=IntakePortalBudgetStatus.PENDING)
            .first()
        )
        is_new = budget is None
        previous = None if is_new else (budget.estimated_hours, budget.note or "")
        if previous is not None and previous == (hours, note):
            return None, "Nada mudou: altere as horas ou a justificativa antes de reenviar."
        if is_new:
            budget = IntakePortalBudget(
                issue_id=intake_issue.issue_id,
                project_id=intake_issue.project_id,
                workspace_id=intake_issue.workspace_id,
            )
        budget.estimated_hours = hours
        budget.note = note
        budget.status = IntakePortalBudgetStatus.PENDING
        budget.requested_at = timezone.now()
        try:
            if created_by_id is not None and is_new:
                budget.save(created_by_id=created_by_id)
            else:
                budget.save()
        except IntegrityError:
            # Someone sent another estimate at the same moment: theirs is the pending one.
            return None, "Já existe um orçamento aguardando o cliente. Atualize a página e revise esse."
        record_budget_event(
            budget, "sent" if is_new else "revised", actor_id=actor_id or created_by_id, previous=previous
        )

    send_portal_budget_request.delay(str(intake_issue.issue_id), budget_id=str(budget.id))
    return budget, None


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def note_blocks(text):
    """Split an estimate note into paragraphs and lists (same rules as the screens).

    Lines starting with "-", "*" or "•" make a bullet list, "1." or "1)" a numbered list; blank lines
    separate paragraphs and single line breaks are kept. Returns [(kind, [lines])], kind in p/ul/ol.
    """
    blocks = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        bullet, numbered = _BULLET.match(line), _NUMBERED.match(line)
        kind, content = ("ul", bullet.group(1)) if bullet else ("ol", numbered.group(1)) if numbered else ("p", line)
        if kind == "p" and not line.strip():
            blocks.append(None)
            continue
        if blocks and blocks[-1] is not None and blocks[-1][0] == kind:
            blocks[-1][1].append(content)
        else:
            blocks.append((kind, [content]))
    return [block for block in blocks if block is not None]


def note_to_html(text):
    """Estimate note as safe HTML for e-mails: escaped, with paragraphs, lists and **bold**."""
    from html import escape

    def inline(value):
        return _BOLD.sub(r"<strong>\1</strong>", escape(value))

    parts = []
    for kind, lines in note_blocks(text):
        if kind == "p":
            parts.append('<p style="margin:0 0 8px">' + "<br>".join(inline(line) for line in lines) + "</p>")
        else:
            items = "".join(f'<li style="margin:0 0 4px">{inline(line)}</li>' for line in lines)
            parts.append(f'<{kind} style="margin:0 0 8px;padding-left:20px">{items}</{kind}>')
    return "".join(parts)
