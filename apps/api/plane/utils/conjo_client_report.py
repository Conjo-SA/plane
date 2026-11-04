# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: activity report sent to the client (what was done and where the hours went).

Read only: it gathers the time logged on the client's work items in a period and the hour package
statement. Rules:

- Only work items of the client (``billing.client_issues``) in projects the person issuing the report
  can see. Items of other clients, of other workspaces and without a client never enter.
- Items marked ``internal`` never enter (internal work is not reported to the client).
- Items without a kind do not enter either: the report could not say whether the hours were debited.
  They are listed in ``warnings`` (shown only to whoever issues the report, never printed) so the
  team can classify them and issue the report again.
- The member who logged the time is not exposed; the report is signed by the contract owner.
- Evolution with an approved estimate counts the approved hours, because that is what the client pays:
  each estimate enters on the date of its open package debit (the approval date when the client has no
  package), and the time logged on the item stays only as the description of the work, adding no hours.
  An estimate whose debit was reversed is no longer paid, so it does not count. A maintenance item is
  not debited, so it keeps the logged hours. The logged hours stay on the card and in ``time_report``.
"""

# Python imports
import datetime
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

# Module imports
from plane.utils import conjo_billing as billing

ZERO = Decimal("0")
REPORTED_KINDS = ("evolution", "maintenance")
MAX_ROWS = 1000
MAX_HIGHLIGHTS = 4
MAX_SYSTEMS = 6
MAX_NEXT_STEPS = 6
SUMMARY_CHARS = 320
NO_SYSTEM = "Geral"
OTHER_SYSTEMS = "Outros"
APPROVED_ESTIMATE = "Orçamento aprovado"


def report_number(client, start, end):
    """Deterministic number: the same client and period always get the same number.

    ``RA-AAAA-MM-XXXXXX`` for a calendar month (``XXXXXX`` comes from the client id), and
    ``RA-AAAAMMDD-AAAAMMDD-XXXXXX`` for any other period. Nothing is stored, so issuing the report
    again (or by two people) never creates gaps or duplicates.
    """
    suffix = client.id.hex[:6].upper()
    is_month = start.day == 1 and end == billing.lot_expiry(start, 1)
    if is_month:
        return f"RA-{start:%Y-%m}-{suffix}"
    return f"RA-{start:%Y%m%d}-{end:%Y%m%d}-{suffix}"


def _hours(minutes):
    return str(billing.hours_of(minutes))


def _minutes(minutes):
    """Whole minutes for the payload; an estimate can fall between minutes (1.01 h = 60.6 min)."""
    return int(Decimal(minutes).to_integral_value(ROUND_HALF_UP))


def _summary(descriptions):
    """The item's descriptions in order, without repetitions, cut at a word boundary."""
    seen = []
    for text in descriptions:
        text = " ".join(str(text or "").split())
        if text and text not in seen:
            seen.append(text)
    joined = " ".join(t if t.endswith((".", "!", "?")) else f"{t}." for t in seen)
    if len(joined) <= SUMMARY_CHARS:
        return joined
    cut = joined[:SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(",;:.")
    return f"{cut}…"


def _owner(contract):
    user = getattr(contract, "created_by", None) if contract else None
    if user is None:
        return "Conjo SA"
    name = " ".join(p for p in (user.first_name, user.last_name) if p).strip() or user.display_name or ""
    return f"{name} (Conjo SA)" if name else "Conjo SA"


def _contract_for_period(client, start, end):
    """The package in force at the end of the period (a replaced one keeps its statement)."""
    from plane.db.models import ClientContract

    on = min(end, billing.today())
    return (
        ClientContract.objects.filter(client=client, starts_on__lte=on)
        .exclude(ends_on__lt=start)
        .select_related("created_by")
        .order_by("-is_active", "-starts_on", "-created_at")
        .first()
    )


def _package(contract, start, end):
    """Package numbers at the end of the period, from the statement (never from today's balance)."""
    from plane.db.models import HourLedgerEntry

    if contract is None:
        return None
    entries = list(
        HourLedgerEntry.objects.filter(contract=contract, occurred_on__lte=end).order_by("occurred_on", "created_at")
    )
    balance = sum((billing.effect(e) for e in entries), ZERO)
    used = -sum(
        (
            e.hours
            for e in entries
            if e.occurred_on >= start and e.kind in (HourLedgerEntry.DEBIT, HourLedgerEntry.REVERSAL)
        ),
        ZERO,
    )
    excess = sum((e.hours for e in entries if e.occurred_on >= start and e.kind == HourLedgerEntry.EXCESS), ZERO)
    # Lots still valid after the period make up what the client can use (a lot is written off on its
    # expiry date, so one expiring on the last day is already out of the balance).
    lots = [e for e in entries if e.expires_on and e.expires_on > end and e.hours > 0]
    contracted = sum((lot.hours for lot in lots), ZERO)
    balance = max(balance, ZERO)
    used = max(used, ZERO)
    previous = max(contracted - used - balance, ZERO)
    contracted = max(contracted, previous + used + balance)
    return {
        "contract_name": contract.name,
        "hours_per_month": str(contract.hours_per_month),
        "contracted": str(contracted),
        "used_before": str(previous),
        "used_in_period": str(used),
        "balance": str(balance),
        "excess_in_period": str(abs(excess)),
        "valid_until": max(lot.expires_on for lot in lots).isoformat() if lots else None,
        "next_expiry": min(lot.expires_on for lot in lots).isoformat() if lots else None,
    }


def build_client_report(client, start, end, visible_project_ids):
    """The report payload. ``visible_project_ids``: projects whose items the issuer may see."""
    from plane.db.models import (
        ClientLabel,
        HourLedgerEntry,
        IntakePortalBudget,
        IssueLabel,
        IssueWorkKind,
        IssueWorkLog,
    )

    visible = {str(p) for p in visible_project_ids}
    client_issue_ids = billing.client_issues(client).filter(workspace_id=client.workspace_id).values("id")
    logs = list(
        IssueWorkLog.objects.filter(
            workspace_id=client.workspace_id,
            issue_id__in=client_issue_ids,
            project_id__in=visible,
            issue__project_id__in=visible,
            logged_on__gte=start,
            logged_on__lte=end,
        )
        .select_related("issue__project", "issue__state")
        .order_by("logged_on", "created_at")
    )
    approved = list(
        IntakePortalBudget.objects.filter(
            workspace_id=client.workspace_id,
            issue_id__in=client_issue_ids,
            project_id__in=visible,
            issue__project_id__in=visible,
            status="APPROVED",
        )
        .select_related("issue__project", "issue__state")
        .order_by("approved_at", "created_at")
    )
    issue_ids = {log.issue_id for log in logs} | {budget.issue_id for budget in approved}
    kinds = dict(IssueWorkKind.objects.filter(issue_id__in=issue_ids).values_list("issue_id", "kind"))
    # An approved estimate is an evolution unless the team said otherwise (same rule as the debit, which
    # does not mark the kind when the client has no package).
    for budget in approved:
        kinds.setdefault(budget.issue_id, "evolution")

    # An approved estimate is final, so a reversal only shows in the statement. Without any debit of this
    # client (no package) it counts from its approval; with debits, only an open one keeps it paid. Debits
    # of a previous client of the item say nothing about this one.
    debited, debit_dates = set(), {}
    for budget_id, occurred_on, reversal_id in (
        HourLedgerEntry.objects.filter(
            budget_id__in=[b.id for b in approved], kind=HourLedgerEntry.DEBIT, contract__client_id=client.id
        )
        .order_by("created_at")
        .values_list("budget_id", "occurred_on", "reversals__id")
    ):
        debited.add(budget_id)
        if reversal_id is None:
            debit_dates[budget_id] = occurred_on
    estimates = [
        (budget, debit_dates.get(budget.id) or billing.local_date(budget.approved_at or budget.created_at))
        for budget in approved
        if kinds[budget.issue_id] == "evolution" and (budget.id in debit_dates or budget.id not in debited)
    ]
    budgeted = {budget.issue_id for budget, _ in estimates}

    reported = [
        {
            "id": log.id,
            "date": log.logged_on,
            "issue": log.issue,
            "minutes": 0 if log.issue_id in budgeted else log.minutes,
            "description": log.description,
            "budgeted": log.issue_id in budgeted,
        }
        for log in logs
        if kinds.get(log.issue_id) in REPORTED_KINDS
    ]
    for budget, counted_on in estimates:
        if start <= counted_on <= end:
            reported.append(
                {
                    "id": budget.id,
                    "date": counted_on,
                    "issue": budget.issue,
                    "minutes": budget.estimated_hours * 60,
                    "description": APPROVED_ESTIMATE,
                    "budgeted": False,
                }
            )
    reported.sort(key=lambda entry: entry["date"])

    unclassified = OrderedDict()
    for log in logs:
        if log.issue_id not in kinds:
            item = unclassified.setdefault(log.issue_id, {"issue": log.issue, "minutes": 0})
            item["minutes"] += log.minutes

    # Systems: the work item's labels, except the ones that identify a client on a shared board.
    reported_ids = {entry["issue"].id for entry in reported}
    client_label_ids = set(
        ClientLabel.objects.filter(workspace_id=client.workspace_id).values_list("label_id", flat=True)
    )
    issue_system = {}
    for issue_id, label_id, name in (
        IssueLabel.objects.filter(issue_id__in=reported_ids, label__deleted_at__isnull=True)
        .values_list("issue_id", "label_id", "label__name")
        .order_by("label__name")
    ):
        if label_id not in client_label_ids and issue_id not in issue_system:
            issue_system[issue_id] = name

    totals = {kind: 0 for kind in REPORTED_KINDS}
    systems = {}
    items = OrderedDict()
    for entry in reported:
        issue_id = entry["issue"].id
        kind = kinds[issue_id]
        totals[kind] += entry["minutes"]
        system = systems.setdefault(issue_system.get(issue_id, NO_SYSTEM), {"evolution": 0, "maintenance": 0})
        system[kind] += entry["minutes"]
        item = items.setdefault(
            issue_id, {"issue": entry["issue"], "kind": kind, "minutes": 0, "descriptions": [], "entries": 0}
        )
        item["minutes"] += entry["minutes"]
        item["entries"] += 1
        item["descriptions"].append(entry["description"])

    def key(issue):
        return f"{issue.project.identifier}-{issue.sequence_id}"

    def is_done(issue):
        return bool(issue.state_id) and issue.state.group == "completed"

    total_minutes = sum(totals.values())

    ranked_systems = sorted(systems.items(), key=lambda pair: -(pair[1]["evolution"] + pair[1]["maintenance"]))
    if len(ranked_systems) > MAX_SYSTEMS:
        rest = {"evolution": 0, "maintenance": 0}
        for _, minutes in ranked_systems[MAX_SYSTEMS - 1 :]:
            rest["evolution"] += minutes["evolution"]
            rest["maintenance"] += minutes["maintenance"]
        ranked_systems = ranked_systems[: MAX_SYSTEMS - 1] + [(OTHER_SYSTEMS, rest)]

    by_kind = []
    for kind in REPORTED_KINDS:
        kind_items = [i for i in items.values() if i["kind"] == kind]
        by_kind.append(
            {
                "kind": kind,
                "minutes": _minutes(totals[kind]),
                "hours": _hours(totals[kind]),
                "items": len(kind_items),
                "done_items": sum(1 for i in kind_items if is_done(i["issue"])),
            }
        )

    highlights = sorted(items.values(), key=lambda i: -i["minutes"])[:MAX_HIGHLIGHTS]

    # In progress and next steps: reported items still open, and estimates waiting for the client.
    next_steps = []
    for item in items.values():
        group = item["issue"].state.group if item["issue"].state_id else None
        if group not in ("completed", "cancelled"):
            next_steps.append({"type": "in_progress", "key": key(item["issue"]), "title": item["issue"].name})
    pending = (
        IntakePortalBudget.objects.filter(
            workspace_id=client.workspace_id,
            issue_id__in=client_issue_ids,
            project_id__in=visible,
            issue__project_id__in=visible,
            status="PENDING",
        )
        .filter(issue_id__in=IssueWorkKind.objects.filter(kind__in=REPORTED_KINDS).values("issue_id"))
        .select_related("issue__project")
        .order_by("created_at")
    )
    for budget in pending[:MAX_NEXT_STEPS]:
        next_steps.append(
            {
                "type": "pending_estimate",
                "key": key(budget.issue),
                "title": budget.issue.name,
                "hours": str(budget.estimated_hours),
            }
        )

    contract = _contract_for_period(client, start, end)
    if contract is not None and contract.is_active:
        billing.refresh_contract(contract)

    warnings = []
    if unclassified:
        warnings.append(
            {
                "type": "unclassified",
                "message": "Itens com horas no período e sem tipo (evolução ou manutenção) ficaram fora do "
                "relatório. Classifique-os e emita de novo.",
                "items": [
                    {
                        "id": str(issue_id),
                        "project_id": str(entry["issue"].project_id),
                        "key": key(entry["issue"]),
                        "title": entry["issue"].name,
                        "hours": _hours(entry["minutes"]),
                    }
                    for issue_id, entry in unclassified.items()
                ],
            }
        )
    hidden = {str(p) for p in billing.client_project_ids(client)} - visible
    if hidden:
        warnings.append(
            {
                "type": "partial",
                "message": "Você não participa de todos os projetos deste cliente: o relatório mostra só os "
                "projetos a que você tem acesso. Peça a um administrador para emitir a versão completa.",
                "items": [],
            }
        )
    if len(reported) > MAX_ROWS:
        warnings.append(
            {
                "type": "truncated",
                "message": f"O detalhamento mostra os primeiros {MAX_ROWS} lançamentos; os totais incluem todos.",
                "items": [],
            }
        )

    issued_on = billing.today()
    return {
        "number": report_number(client, start, end),
        "issued_on": issued_on.isoformat(),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "client": {"id": str(client.id), "name": client.name, "legal_name": client.legal_name},
        "contract": {"name": contract.name} if contract else None,
        "owner": _owner(contract),
        "totals": {
            "minutes": _minutes(total_minutes),
            "hours": _hours(total_minutes),
            "evolution_minutes": _minutes(totals["evolution"]),
            "evolution_hours": _hours(totals["evolution"]),
            "maintenance_minutes": _minutes(totals["maintenance"]),
            "maintenance_hours": _hours(totals["maintenance"]),
            "items": len(items),
            "done_items": sum(1 for i in items.values() if is_done(i["issue"])),
        },
        "package": _package(contract, start, end),
        "by_kind": by_kind,
        "by_system": [
            {
                "name": name,
                "minutes": _minutes(minutes["evolution"] + minutes["maintenance"]),
                "hours": _hours(minutes["evolution"] + minutes["maintenance"]),
                "evolution_minutes": _minutes(minutes["evolution"]),
                "maintenance_minutes": _minutes(minutes["maintenance"]),
            }
            for name, minutes in ranked_systems
        ],
        "highlights": [
            {
                "key": key(item["issue"]),
                "title": item["issue"].name,
                "kind": item["kind"],
                "minutes": _minutes(item["minutes"]),
                "hours": _hours(item["minutes"]),
                # Work on an estimate approved in another period: its hours are not in this one.
                "budgeted": item["issue"].id in budgeted and not item["minutes"],
                "summary": _summary(item["descriptions"]),
                "done": is_done(item["issue"]),
            }
            for item in highlights
        ],
        "rows": [
            {
                "id": str(entry["id"]),
                "date": entry["date"].isoformat(),
                "key": key(entry["issue"]),
                "kind": kinds[entry["issue"].id],
                "title": entry["issue"].name,
                "description": " ".join(str(entry["description"] or "").split()),
                "minutes": _minutes(entry["minutes"]),
                "hours": _hours(entry["minutes"]),
                "budgeted": entry["budgeted"],
            }
            for entry in reported[:MAX_ROWS]
        ],
        "next_steps": next_steps[: MAX_NEXT_STEPS * 2],
        "warnings": warnings,
    }


def parse_period(params, today=None):
    """``from``/``to`` (YYYY-MM-DD); the previous calendar month by default. ``(None, None)`` if invalid."""
    today = today or billing.today()
    first_of_month = billing.month_start(today)
    default_end = first_of_month - datetime.timedelta(days=1)
    default_start = billing.month_start(default_end)
    raw_start, raw_end = params.get("from"), params.get("to")
    try:
        start = datetime.date.fromisoformat(str(raw_start)[:10]) if raw_start else default_start
        end = datetime.date.fromisoformat(str(raw_end)[:10]) if raw_end else default_end
    except ValueError:
        return None, None
    if end < start or (end - start).days > 366:
        return None, None
    return start, end
