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


def serialize_portal_budget(budget):
    """Return the public shape of an hourly estimate, or None."""
    if budget is None:
        return None

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
    }


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

    return list(IntakePortalBudget.objects.filter(issue_id=issue_id).order_by("created_at"))


def current_budget(budgets):
    """The estimate the screens highlight: the pending one, else the latest."""
    pending = [b for b in budgets if b.status == IntakePortalBudgetStatus.PENDING]
    if pending:
        return pending[-1]
    return budgets[-1] if budgets else None


def approved_hours(budgets):
    return sum((b.estimated_hours for b in budgets if b.status == IntakePortalBudgetStatus.APPROVED), Decimal("0"))


def serialize_budget_context(issue_id):
    """``budget`` (the highlighted one), ``budgets`` (history, oldest first) and the approved total."""
    budgets = issue_budgets(issue_id)
    return {
        "budget": serialize_portal_budget(current_budget(budgets)),
        "budgets": [serialize_portal_budget(b) for b in budgets],
        "approved_hours": float(approved_hours(budgets)),
    }


def request_portal_budget(intake_issue, raw_hours, raw_note, created_by_id=None):
    """Send an hourly estimate for a portal ticket and e-mail the requester.

    Shared by the team screen and the MCP so both follow the same rules: the hours are validated, a
    pending estimate is repriced in place, and otherwise a new estimate is created (after a rejection,
    or as an additional estimate after an approval). Approved estimates are never touched.
    Returns (budget, error).
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
