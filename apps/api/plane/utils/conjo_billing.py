# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Hour packages: monthly credits (lots), debits on approved estimates, expirations and the statement.

Rules (agreed with the business):
- A contract credits ``hours_per_month`` every month; each credit is a lot valid for
  ``accumulation_months`` (the October credit with 3 months is usable until December 31).
- Approving an estimate of an evolution debits the estimated hours, consuming the lot that expires first.
  Hours beyond the balance are recorded as excess (for the finance system) and do not change the balance.
- Maintenance and internal work are counted (time logs, reports) but never debited.
"""

# Python imports
import calendar
import datetime
import re
from decimal import ROUND_HALF_UP, Decimal

# Django imports
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

ZERO = Decimal("0")
CENT = Decimal("0.01")


# --------------------------------------------------------------------------- #
# Durations
# --------------------------------------------------------------------------- #

DURATION_RE = re.compile(
    r"^\s*(?:(?P<h>\d+(?:[.,]\d+)?)\s*h(?:oras?)?)?\s*(?:(?P<m>\d+)\s*(?:m(?:in(?:utos?)?)?)?)?\s*$",
    re.IGNORECASE,
)


def parse_duration(text):
    """Minutes from "1h30", "1h 30m", "90m", "1,5h", "45min" or "2"; ``None`` when invalid."""
    if text is None:
        return None
    if isinstance(text, int):
        return text if text > 0 else None
    raw = str(text).strip()
    if not raw:
        return None
    if raw.isdigit():
        # A bare number is minutes ("90"), unless it is small enough to read as hours ("2").
        value = int(raw)
        minutes = value * 60 if value <= 12 else value
        return minutes or None
    match = DURATION_RE.match(raw)
    if not match or not (match.group("h") or match.group("m")):
        return None
    hours = Decimal((match.group("h") or "0").replace(",", "."))
    minutes = int((hours * 60).to_integral_value(ROUND_HALF_UP)) + int(match.group("m") or 0)
    return minutes or None


def format_minutes(minutes):
    hours, rest = divmod(int(minutes or 0), 60)
    if hours and rest:
        return f"{hours}h{rest:02d}"
    return f"{hours}h" if hours else f"{rest}min"


def hours_of(minutes):
    return (Decimal(minutes or 0) / 60).quantize(CENT, ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #


def month_start(day):
    return day.replace(day=1)


def add_months(day, months):
    years, month = divmod(day.month - 1 + months, 12)
    return datetime.date(day.year + years, month + 1, 1)


def lot_expiry(period, accumulation_months):
    """Last day a credit for ``period`` (a month) can be used."""
    last_month = add_months(period, max(int(accumulation_months or 1), 1) - 1)
    return last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])


def today():
    return timezone.localdate()


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #


def active_contract(client, on=None):
    from plane.db.models import ClientContract

    on = on or today()
    return (
        ClientContract.objects.filter(client=client, is_active=True, starts_on__lte=on)
        .exclude(ends_on__lt=on)
        .order_by("-starts_on")
        .first()
    )


def client_for_project(project_id):
    from plane.db.models import ClientProject

    link = ClientProject.objects.filter(project_id=project_id).select_related("client").first()
    return link.client if link else None


def contract_for_issue(issue, on=None):
    client = client_for_project(issue.project_id)
    return active_contract(client, on) if client else None


def work_kind(issue):
    from plane.db.models import IssueWorkKind

    entry = IssueWorkKind.objects.filter(issue_id=issue.id).first()
    return entry.kind if entry else None


# --------------------------------------------------------------------------- #
# Balance and lots
# --------------------------------------------------------------------------- #


def effect(entry):
    """Effect of a statement entry on the balance (excess hours are informational)."""
    from plane.db.models import HourLedgerEntry

    return ZERO if entry.kind == HourLedgerEntry.EXCESS else entry.hours


def available_lots(contract, on=None, lock=False):
    from plane.db.models import HourLedgerEntry

    on = on or today()
    lots = HourLedgerEntry.objects.filter(contract=contract, remaining__gt=0, expires_on__gte=on)
    if lock:
        lots = lots.select_for_update()
    return lots.order_by("expires_on", "period", "created_at")


def balance(contract, on=None):
    total = available_lots(contract, on).aggregate(total=Sum("remaining"))["total"]
    return total or ZERO


def consume(contract, hours, on):
    """Take ``hours`` from the lots that expire first. Returns ``(allocations, consumed)``."""
    remaining = Decimal(hours)
    allocations = []
    for lot in available_lots(contract, on, lock=True):
        if remaining <= 0:
            break
        take = min(lot.remaining, remaining)
        lot.remaining -= take
        lot.save(update_fields=["remaining", "updated_at"])
        allocations.append({"lot": str(lot.id), "hours": str(take)})
        remaining -= take
    return allocations, Decimal(hours) - remaining


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


@transaction.atomic
def ensure_monthly_credits(contract, on=None):
    """Credit every month from the contract start (or its creation) up to ``on``. Idempotent."""
    from plane.db.models import HourLedgerEntry

    on = on or today()
    first = month_start(contract.starts_on)
    created = month_start(timezone.localdate(contract.created_at)) if contract.created_at else first
    # A contract registered today for a client that started long ago does not invent past credits:
    # the current balance comes in as an adjustment.
    period = max(first, created)
    last = month_start(on) if on.day >= contract.credit_day else add_months(month_start(on), -1)
    if contract.ends_on:
        last = min(last, month_start(contract.ends_on))
    existing = set(
        HourLedgerEntry.objects.filter(contract=contract, kind=HourLedgerEntry.CREDIT).values_list("period", flat=True)
    )
    created_entries = []
    while period <= last:
        if period not in existing:
            created_entries.append(
                HourLedgerEntry.objects.create(
                    workspace_id=contract.workspace_id,
                    contract=contract,
                    kind=HourLedgerEntry.CREDIT,
                    hours=contract.hours_per_month,
                    remaining=contract.hours_per_month,
                    period=period,
                    expires_on=lot_expiry(period, contract.accumulation_months),
                    occurred_on=period.replace(day=min(contract.credit_day, 28)),
                    note=f"Crédito mensal de {period.strftime('%m/%Y')}",
                )
            )
        period = add_months(period, 1)
    return created_entries


@transaction.atomic
def expire_lots(contract, on=None):
    """Write off what is left of lots past their validity."""
    from plane.db.models import HourLedgerEntry

    on = on or today()
    expired = []
    for lot in HourLedgerEntry.objects.select_for_update().filter(
        contract=contract, remaining__gt=0, expires_on__lt=on
    ):
        left = lot.remaining
        lot.remaining = ZERO
        lot.save(update_fields=["remaining", "updated_at"])
        label = lot.period.strftime("%m/%Y") if lot.period else lot.occurred_on.strftime("%d/%m/%Y")
        expired.append(
            HourLedgerEntry.objects.create(
                workspace_id=contract.workspace_id,
                contract=contract,
                kind=HourLedgerEntry.EXPIRATION,
                hours=-left,
                occurred_on=lot.expires_on,
                note=f"Sobra do crédito de {label} não usada no prazo",
                allocations=[{"lot": str(lot.id), "hours": str(left)}],
            )
        )
    return expired


def open_debit(issue):
    from plane.db.models import HourLedgerEntry

    return (
        HourLedgerEntry.objects.filter(issue_id=issue.id, kind=HourLedgerEntry.DEBIT, reversals__isnull=True)
        .order_by("-created_at")
        .first()
    )


@transaction.atomic
def debit_for_estimate(issue, hours, approved_by_email="", on=None):
    """Debit an approved estimate (evolution only). Idempotent per work item.

    Returns the debit entry, or ``None`` when nothing is debited (no contract, maintenance/internal work,
    already debited).
    """
    from plane.db.models import HourLedgerEntry, IssueWorkKind

    on = on or today()
    kind = work_kind(issue)
    if kind in (IssueWorkKind.MAINTENANCE, IssueWorkKind.INTERNAL):
        return None
    contract = contract_for_issue(issue, on)
    if contract is None:
        return None
    if kind is None:
        # An approved estimate is an evolution unless the team said otherwise.
        IssueWorkKind.objects.create(issue=issue, project_id=issue.project_id, kind=IssueWorkKind.EVOLUTION)
    if open_debit(issue) is not None:
        return None

    hours = Decimal(hours).quantize(CENT, ROUND_HALF_UP)
    ensure_monthly_credits(contract, on)
    expire_lots(contract, on)
    allocations, consumed = consume(contract, hours, on)
    who = f" por {approved_by_email}" if approved_by_email else ""
    debit = HourLedgerEntry.objects.create(
        workspace_id=contract.workspace_id,
        contract=contract,
        kind=HourLedgerEntry.DEBIT,
        hours=-consumed,
        occurred_on=on,
        issue=issue,
        allocations=allocations,
        approved_by_email=approved_by_email or "",
        note=f"Orçamento de {format_minutes(int(hours * 60))} aprovado{who}",
    )
    excess = hours - consumed
    if excess > 0:
        HourLedgerEntry.objects.create(
            workspace_id=contract.workspace_id,
            contract=contract,
            kind=HourLedgerEntry.EXCESS,
            hours=excess,
            occurred_on=on,
            issue=issue,
            approved_by_email=approved_by_email or "",
            note=f"{format_minutes(int(excess * 60))} além do saldo do pacote",
        )
    return debit


@transaction.atomic
def reverse_debit(debit, note="", on=None):
    """Give a debit's hours back to its lots (the ones still valid). Returns the reversal entry."""
    from plane.db.models import HourLedgerEntry

    on = on or today()
    if debit.kind != HourLedgerEntry.DEBIT or debit.reversals.exists():
        return None
    restored = ZERO
    for allocation in debit.allocations or []:
        lot = HourLedgerEntry.objects.select_for_update().filter(pk=allocation.get("lot")).first()
        if lot is None or (lot.expires_on and lot.expires_on < on):
            continue
        hours = Decimal(allocation.get("hours") or "0")
        lot.remaining = (lot.remaining or ZERO) + hours
        lot.save(update_fields=["remaining", "updated_at"])
        restored += hours
    # The excess of that estimate no longer applies either.
    HourLedgerEntry.objects.filter(
        contract=debit.contract, kind=HourLedgerEntry.EXCESS, issue_id=debit.issue_id, exported_at__isnull=True
    ).delete()
    return HourLedgerEntry.objects.create(
        workspace_id=debit.workspace_id,
        contract=debit.contract,
        kind=HourLedgerEntry.REVERSAL,
        hours=restored,
        occurred_on=on,
        issue_id=debit.issue_id,
        reversed_entry=debit,
        note=note or "Estorno do débito",
    )


@transaction.atomic
def adjust(contract, hours, note, on=None):
    """Manual adjustment: positive opens a lot valid like a monthly credit; negative consumes lots."""
    from plane.db.models import HourLedgerEntry

    on = on or today()
    hours = Decimal(hours).quantize(CENT, ROUND_HALF_UP)
    if hours > 0:
        period = month_start(on)
        return HourLedgerEntry.objects.create(
            workspace_id=contract.workspace_id,
            contract=contract,
            kind=HourLedgerEntry.ADJUSTMENT,
            hours=hours,
            remaining=hours,
            period=period,
            expires_on=lot_expiry(period, contract.accumulation_months),
            occurred_on=on,
            note=note,
        )
    allocations, consumed = consume(contract, -hours, on)
    return HourLedgerEntry.objects.create(
        workspace_id=contract.workspace_id,
        contract=contract,
        kind=HourLedgerEntry.ADJUSTMENT,
        hours=-consumed,
        occurred_on=on,
        allocations=allocations,
        note=note,
    )


def refresh_contract(contract, on=None):
    """Bring a contract's statement up to date (credits due, expirations)."""
    ensure_monthly_credits(contract, on)
    expire_lots(contract, on)


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #


def package_summary(contract, on=None):
    """Numbers shown on the client page, the statement header and the portal."""
    from plane.db.models import HourLedgerEntry

    on = on or today()
    lots = list(available_lots(contract, on))
    month = month_start(on)
    debited = (
        HourLedgerEntry.objects.filter(contract=contract, kind=HourLedgerEntry.DEBIT, occurred_on__gte=month).aggregate(
            total=Sum("hours")
        )["total"]
        or ZERO
    )
    reversed_ = (
        HourLedgerEntry.objects.filter(
            contract=contract, kind=HourLedgerEntry.REVERSAL, occurred_on__gte=month
        ).aggregate(total=Sum("hours"))["total"]
        or ZERO
    )
    available = sum((lot.remaining for lot in lots), ZERO)
    threshold = (contract.hours_per_month * contract.low_balance_percent / 100).quantize(CENT, ROUND_HALF_UP)
    return {
        "contract_id": str(contract.id),
        "contract_name": contract.name,
        "hours_per_month": str(contract.hours_per_month),
        "accumulation_months": contract.accumulation_months,
        "max_balance": str(contract.hours_per_month * contract.accumulation_months),
        "available": str(available),
        "debited_this_month": str(-(debited + reversed_)),
        "low_balance": available <= threshold,
        "lots": [
            {
                "id": str(lot.id),
                "kind": lot.kind,
                "period": lot.period.isoformat() if lot.period else None,
                "hours": str(lot.hours),
                "remaining": str(lot.remaining),
                "expires_on": lot.expires_on.isoformat() if lot.expires_on else None,
            }
            for lot in lots
        ],
    }


def statement(contract, start=None, end=None):
    """Entries between ``start`` and ``end`` (inclusive), newest first, each with the balance after it."""
    from plane.db.models import HourLedgerEntry

    entries = list(HourLedgerEntry.objects.filter(contract=contract).order_by("occurred_on", "created_at"))
    running = ZERO
    rows = []
    for entry in entries:
        running += effect(entry)
        if (start and entry.occurred_on < start) or (end and entry.occurred_on > end):
            continue
        rows.append((entry, running))
    rows.reverse()
    return rows


def portal_package(project_id, email):
    """Package numbers for the public portal, only for a contact registered on the client."""
    from plane.db.models import ClientContact

    client = client_for_project(project_id)
    if client is None or not email:
        return None
    if not ClientContact.objects.filter(client=client, email__iexact=email).exists():
        return None
    contract = active_contract(client)
    if contract is None:
        return None
    refresh_contract(contract)
    summary = package_summary(contract)
    lots = summary["lots"]
    return {
        "client_name": client.name,
        "available": summary["available"],
        "hours_per_month": summary["hours_per_month"],
        "accumulation_months": summary["accumulation_months"],
        "next_expiring": {"hours": lots[0]["remaining"], "expires_on": lots[0]["expires_on"]} if lots else None,
    }
