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
from zoneinfo import ZoneInfo

# Django imports
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

ZERO = Decimal("0")
CENT = Decimal("0.01")
# Largest amount accepted for a single entry (fits the ledger columns with room for sums).
MAX_HOURS = Decimal("9999")
# Months, expirations and "today" follow the business calendar, not the server's UTC clock.
BILLING_TZ = ZoneInfo(getattr(settings, "CONJO_BILLING_TIMEZONE", "America/Sao_Paulo"))


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
    return timezone.localdate(timezone=BILLING_TZ)


def local_date(moment):
    return timezone.localdate(moment, timezone=BILLING_TZ)


def parse_hours(value, allow_negative=False):
    """Hours typed by a person ("8", "1,5", "-2"): ``None`` unless finite, non zero and within MAX_HOURS."""
    try:
        hours = Decimal(str(value).strip().replace(",", "."))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not hours.is_finite():
        return None
    hours = hours.quantize(CENT, ROUND_HALF_UP)
    if hours == 0 or abs(hours) > MAX_HOURS or (hours < 0 and not allow_negative):
        return None
    return hours


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
    """The client a whole project belongs to (projects dedicated to one client)."""
    from plane.db.models import ClientProject

    link = ClientProject.objects.filter(project_id=project_id).select_related("client").first()
    return link.client if link else None


def clients_for_project(project_id):
    """Clients with work in a project: the project's own client and the clients of its labels (shared boards)."""
    from plane.db.models import Client

    return Client.objects.filter(
        Q(client_projects__project_id=project_id, client_projects__deleted_at__isnull=True)
        | Q(client_labels__label__project_id=project_id, client_labels__deleted_at__isnull=True)
    ).distinct()


def client_resolution(issue):
    """Who a work item is for: ``(client, via, label_name, ambiguous)``.

    A label linked to a client wins (a board shared by several clients, like MAN, tells them apart by
    label); otherwise the client of the whole project. Labels of two different clients are ambiguous:
    no client is applied, so nothing is debited by guesswork.
    """
    from plane.db.models import ClientLabel, IssueLabel

    label_ids = IssueLabel.objects.filter(issue_id=issue.id).values("label_id")
    links = {}
    for link in ClientLabel.objects.filter(label_id__in=label_ids).select_related("client", "label"):
        links.setdefault(link.client_id, link)
    if len(links) > 1:
        return None, None, None, True
    if links:
        link = next(iter(links.values()))
        return link.client, "label", link.label.name, False
    client = client_for_project(issue.project_id)
    if client is not None:
        return client, "project", None, False
    return None, None, None, False


def client_for_issue(issue):
    return client_resolution(issue)[0]


def client_issues(client):
    """Work items of a client (same rule as ``client_resolution``), as a queryset usable in subqueries."""
    from plane.db.models import ClientLabel, Issue, IssueLabel

    own_labels = ClientLabel.objects.filter(client=client).values("label_id")
    other_labels = ClientLabel.objects.exclude(client=client).values("label_id")
    with_own = IssueLabel.objects.filter(label_id__in=own_labels).values("issue_id")
    with_other = IssueLabel.objects.filter(label_id__in=other_labels).values("issue_id")
    projects = client.client_projects.values("project_id")
    return Issue.objects.filter((Q(id__in=with_own) | Q(project_id__in=projects)) & ~Q(id__in=with_other))


def client_project_ids(client):
    """Projects where the client has work: its own projects and the projects of its labels."""
    from plane.db.models import ClientLabel

    own = set(client.client_projects.values_list("project_id", flat=True))
    shared = set(ClientLabel.objects.filter(client=client).values_list("label__project_id", flat=True))
    return own | shared


def contract_for_issue(issue, on=None):
    client = client_for_issue(issue)
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


def lock_contract(contract):
    """Serialize every change to a contract's statement (credits, debits, reversals, adjustments).

    Pages fire several requests at once and each one brings the statement up to date; without this
    two of them could credit the same month twice. Must run inside a transaction.
    """
    from plane.db.models import ClientContract

    return ClientContract.objects.select_for_update().get(pk=contract.pk)


@transaction.atomic
def ensure_monthly_credits(contract, on=None):
    """Credit every month from the contract start (or its creation) up to ``on``. Idempotent."""
    from plane.db.models import HourLedgerEntry

    on = on or today()
    contract = lock_contract(contract)
    if not contract.is_active:
        # A replaced or paused package earns nothing; reactivating it does not backfill the gap either.
        return []
    first = month_start(contract.starts_on)
    created = month_start(local_date(contract.created_at)) if contract.created_at else first
    # A contract registered today for a client that started long ago does not invent past credits:
    # the current balance comes in as an adjustment.
    period = max(first, created)
    last = month_start(on) if on.day >= contract.credit_day else add_months(month_start(on), -1)
    if contract.ends_on:
        last = min(last, month_start(contract.ends_on))
    # One monthly credit per client and month, across contracts: a package that replaces another in
    # the middle of a month starts crediting the following month (the old one already credited this one).
    existing = set(
        HourLedgerEntry.objects.filter(contract__client_id=contract.client_id, kind=HourLedgerEntry.CREDIT).values_list(
            "period", flat=True
        )
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
    lock_contract(contract)
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
    # Checked again under the lock: two approvals (or kind changes) at once debit only once.
    contract = lock_contract(contract)
    if kind is None:
        # An approved estimate is an evolution unless the team said otherwise.
        IssueWorkKind.objects.get_or_create(
            issue=issue, defaults={"project_id": issue.project_id, "kind": IssueWorkKind.EVOLUTION}
        )
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
    lock_contract(debit.contract)
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
    # The excess of that estimate no longer applies either. What finance already received gets a
    # counter-entry instead of disappearing, so the next export cancels it.
    excess = HourLedgerEntry.objects.filter(
        contract=debit.contract, kind=HourLedgerEntry.EXCESS, issue_id=debit.issue_id, hours__gt=0
    )
    excess.filter(exported_at__isnull=True).delete()
    exported = excess.filter(exported_at__isnull=False).aggregate(total=Sum("hours"))["total"] or ZERO
    cancelled = (
        HourLedgerEntry.objects.filter(
            contract=debit.contract, kind=HourLedgerEntry.EXCESS, issue_id=debit.issue_id, hours__lt=0
        ).aggregate(total=Sum("hours"))["total"]
        or ZERO
    )
    if exported + cancelled > 0:
        HourLedgerEntry.objects.create(
            workspace_id=debit.workspace_id,
            contract=debit.contract,
            kind=HourLedgerEntry.EXCESS,
            hours=-(exported + cancelled),
            occurred_on=on,
            issue_id=debit.issue_id,
            note="Excedente cancelado pelo estorno",
        )
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
    """Manual adjustment: positive opens a lot valid like a monthly credit; negative consumes lots.

    A negative adjustment larger than the balance raises ``ValueError`` (nothing is written).
    """
    from plane.db.models import HourLedgerEntry

    on = on or today()
    hours = Decimal(hours).quantize(CENT, ROUND_HALF_UP)
    contract = lock_contract(contract)
    if hours < 0 and -hours > balance(contract, on):
        raise ValueError("insufficient balance")
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


@transaction.atomic
def refresh_contract(contract, on=None):
    """Bring a contract's statement up to date (credits due, expirations)."""
    ensure_monthly_credits(contract, on)
    expire_lots(contract, on)


@transaction.atomic
def close_contract(contract, replaced_by=None, on=None):
    """End a package: what is left moves to the package that replaces it (same expiry), or expires.

    Leaving the old lots alive would make hours disappear silently, since only active contracts are
    refreshed.
    """
    from plane.db.models import HourLedgerEntry

    on = on or today()
    contract = lock_contract(contract)
    refresh_contract(contract, on)
    moved = ZERO
    for lot in available_lots(contract, on, lock=True):
        left = lot.remaining
        lot.remaining = ZERO
        lot.save(update_fields=["remaining", "updated_at"])
        label = lot.period.strftime("%m/%Y") if lot.period else lot.occurred_on.strftime("%d/%m/%Y")
        target = f"transferida para {replaced_by.name}" if replaced_by else "encerrada com o contrato"
        HourLedgerEntry.objects.create(
            workspace_id=contract.workspace_id,
            contract=contract,
            kind=HourLedgerEntry.EXPIRATION,
            hours=-left,
            occurred_on=on,
            note=f"Sobra do crédito de {label} {target}",
            allocations=[{"lot": str(lot.id), "hours": str(left)}],
        )
        if replaced_by is not None:
            HourLedgerEntry.objects.create(
                workspace_id=replaced_by.workspace_id,
                contract=replaced_by,
                kind=HourLedgerEntry.ADJUSTMENT,
                hours=left,
                remaining=left,
                period=lot.period,
                expires_on=lot.expires_on,
                occurred_on=on,
                note=f"Saldo de {label} trazido de {contract.name}",
            )
        moved += left
    contract.is_active = False
    if not contract.ends_on or contract.ends_on > on:
        contract.ends_on = on
    contract.save(update_fields=["is_active", "ends_on", "updated_at"])
    return moved


def kind_change_touches_statement(issue):
    """Whether changing the work kind would debit or give back client hours (an admin decision)."""
    from plane.db.models import IntakePortalBudget

    if open_debit(issue) is not None:
        return True
    return (
        contract_for_issue(issue) is not None
        and IntakePortalBudget.objects.filter(issue_id=issue.id, status="APPROVED").exists()
    )


@transaction.atomic
def change_work_kind(issue, kind, reason=""):
    """Set evolution, maintenance or internal and keep the statement consistent with it.

    Leaving evolution reverses the open debit; coming back to it debits the approved estimate again.
    """
    from plane.db.models import IntakePortalBudget, IssueWorkKind

    IssueWorkKind.objects.update_or_create(issue=issue, defaults={"kind": kind, "project_id": issue.project_id})
    debit = open_debit(issue)
    if kind != IssueWorkKind.EVOLUTION and debit is not None:
        label = dict(IssueWorkKind.KIND_CHOICES)[kind]
        reverse_debit(debit, note=f"Tipo alterado para {label}: não desconta do pacote{reason}")
    elif kind == IssueWorkKind.EVOLUTION and debit is None:
        budget = IntakePortalBudget.objects.filter(issue_id=issue.id, status="APPROVED").first()
        if budget is not None:
            debit_for_estimate(issue, budget.estimated_hours, budget.approved_by_email or "")


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
    # Only reversals of this month's debits count, so the number never goes below zero.
    reversed_ = (
        HourLedgerEntry.objects.filter(
            contract=contract,
            kind=HourLedgerEntry.REVERSAL,
            occurred_on__gte=month,
            reversed_entry__occurred_on__gte=month,
        ).aggregate(total=Sum("hours"))["total"]
        or ZERO
    )
    available = sum((lot.remaining for lot in lots), ZERO)
    # Everything that expires on the first expiry date (lots often share it, e.g. a credit and an adjustment).
    first_expiry = lots[0].expires_on if lots else None
    next_expiring = (
        {
            "hours": str(sum((lot.remaining for lot in lots if lot.expires_on == first_expiry), ZERO)),
            "expires_on": first_expiry.isoformat() if first_expiry else None,
        }
        if lots
        else None
    )
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
        "next_expiring": next_expiring,
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


def can_approve_estimate(issue, email):
    """Approving debits the client's package, so only contacts marked "can approve" may do it.

    Work items without a client keep the original rule (whoever opened the ticket decides).
    """
    from plane.db.models import ClientContact

    client = client_for_issue(issue)
    if client is None:
        return True
    return bool(email) and ClientContact.objects.filter(client=client, email__iexact=email, can_approve=True).exists()


def client_for_contact(project_id, email):
    """The client of a requester in a project, by their registered e-mail (None when unknown or ambiguous)."""
    from plane.db.models import ClientContact

    if not email:
        return None
    client_ids = set(
        ClientContact.objects.filter(email__iexact=email, client__in=clients_for_project(project_id)).values_list(
            "client_id", flat=True
        )
    )
    if len(client_ids) != 1:
        return None
    from plane.db.models import Client

    return Client.objects.filter(pk=client_ids.pop()).first()


def label_for_requester(project_id, email):
    """The label that identifies a requester's client on a shared board, so the ticket arrives tagged.

    Only when the requester is a registered contact and their client has exactly one label there.
    """
    from plane.db.models import ClientLabel

    client = client_for_contact(project_id, email)
    if client is None:
        return None
    labels = list(ClientLabel.objects.filter(client=client, label__project_id=project_id).select_related("label")[:2])
    return labels[0].label if len(labels) == 1 else None


@transaction.atomic
def resync_issue_client(issue, on=None):
    """After a work item changes client (its labels changed): the debit follows it.

    The open debit goes back to the old package and the approved estimate is debited from the new one.
    """
    from plane.db.models import IntakePortalBudget, IssueWorkKind

    if work_kind(issue) in (IssueWorkKind.MAINTENANCE, IssueWorkKind.INTERNAL):
        return None
    budget = IntakePortalBudget.objects.filter(issue_id=issue.id, status="APPROVED").first()
    debit = open_debit(issue)
    target = contract_for_issue(issue, on)
    if debit is not None and target is not None and debit.contract_id == target.id:
        return debit
    if debit is not None:
        reverse_debit(debit, note="O cliente da tarefa mudou: horas devolvidas a este pacote", on=on)
    if target is not None and budget is not None:
        return debit_for_estimate(issue, budget.estimated_hours, budget.approved_by_email or "", on=on)
    return None


def portal_package(project_id, email):
    """Package numbers for the public portal, only for a contact registered on the client.

    On a board shared by several clients the requester's e-mail tells which client (and package) is theirs.
    """
    client = client_for_contact(project_id, email)
    if client is None:
        return None
    contract = active_contract(client)
    if contract is None:
        return None
    refresh_contract(contract)
    summary = package_summary(contract)
    return {
        "client_name": client.name,
        "available": summary["available"],
        "hours_per_month": summary["hours_per_month"],
        "accumulation_months": summary["accumulation_months"],
        "next_expiring": summary["next_expiring"],
    }
