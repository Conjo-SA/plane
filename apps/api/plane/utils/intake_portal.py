# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared shaping helpers for the intake portal.

The team facing API and the public portal API both expose the hourly estimate,
so the contract lives here to keep the two surfaces from drifting apart.
"""

from decimal import Decimal, InvalidOperation

from plane.db.models.intake import IntakePortalBudgetStatus

MAX_ESTIMATED_HOURS = Decimal("99999.99")


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
        "requested_at": budget.requested_at,
        "approved_at": budget.approved_at,
        "approved_by_email": budget.approved_by_email,
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
