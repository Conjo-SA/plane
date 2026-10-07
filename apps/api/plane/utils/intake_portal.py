# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared shaping helpers for the intake portal.

The team facing API and the public portal API both expose the hourly estimate,
so the contract lives here to keep the two surfaces from drifting apart.
"""

from decimal import Decimal, InvalidOperation

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


def request_portal_budget(intake_issue, raw_hours, raw_note, created_by_id=None):
    """Send (or reprice) the hourly estimate of a portal ticket and e-mail the requester.

    Shared by the team screen and the MCP so both follow the same rules: the hours are validated, an
    approved estimate is never repriced, and a new request goes back to pending. Returns (budget, error).
    """
    from plane.bgtasks.intake_portal_task import send_portal_budget_request
    from plane.db.models import IntakePortalBudget

    hours, hours_error = parse_estimated_hours(raw_hours)
    if hours_error:
        return None, hours_error

    note = (raw_note or "").strip()[:MAX_BUDGET_NOTE_LENGTH]

    budget = IntakePortalBudget.objects.filter(issue_id=intake_issue.issue_id).first()
    # An approved estimate is a settled agreement, so it is never repriced.
    if budget is not None and budget.status == IntakePortalBudgetStatus.APPROVED:
        return None, "Este orçamento já foi aprovado pelo cliente e não pode ser alterado."

    if budget is None:
        budget = IntakePortalBudget(
            issue_id=intake_issue.issue_id,
            project_id=intake_issue.project_id,
            workspace_id=intake_issue.workspace_id,
        )

    budget.estimated_hours = hours
    budget.note = note
    budget.status = IntakePortalBudgetStatus.PENDING
    budget.requested_at = timezone.now()
    if created_by_id is not None and budget._state.adding:
        budget.save(created_by_id=created_by_id)
    else:
        budget.save()

    send_portal_budget_request.delay(str(intake_issue.issue_id))
    return budget, None
