# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: time spent, clients (CRM), hour packages and development links over MCP.

The tools call the same functions as the app screens, so the rules are the same: one active
package per client, one client per project, debits only for evolutions, adjustments always with a
note, the statement serialized per contract.
"""

# Python imports
import datetime

# Django imports
from django.db.models import Q, Sum
from django.utils import timezone

# Module imports
from plane.app.views import conjo_billing as billing_views
from plane.db.models import (
    Client,
    ClientContact,
    ClientTimelineNote,
    HourLedgerEntry,
    IssueDevelopmentLink,
    IssueWorkKind,
    IssueWorkLog,
    ProjectMember,
)
from plane.mcp.tools.handlers import (
    _PROJECT_PROPERTY,
    _WORK_ITEM_PROPERTY,
    _WORKSPACE_SLUG_PROPERTY,
    MCPToolError,
    _get_issue,
    _get_project,
    _get_workspace,
    _is_uuid,
    _issue_identifier,
    _mcp_actor,
    _parse_date,
)
from plane.mcp.tools.registry import register_tool
from plane.utils import conjo_billing as billing
from plane.utils.conjo_timeline import TYPES as TIMELINE_TYPES
from plane.utils.conjo_timeline import build_timeline

WORK_KINDS = [kind for kind, _ in IssueWorkKind.KIND_CHOICES]
NOTE_KINDS = [kind for kind, _ in ClientTimelineNote.KIND_CHOICES]
VIA_MCP = " (via MCP)"

_CLIENT_PROPERTY = {"client": {"type": "string", "description": "Client UUID, name or CNPJ/CPF"}}


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _get_client(workspace_slug, client):
    workspace = _get_workspace(workspace_slug)
    clients = Client.objects.filter(workspace=workspace)
    value = str(client or "").strip()
    if _is_uuid(value):
        instance = clients.filter(pk=value).first()
    else:
        instance = clients.filter(Q(name__iexact=value) | Q(legal_name__iexact=value) | Q(document=value)).first()
    if instance is None:
        raise MCPToolError(f"Client '{client}' does not exist in workspace '{workspace_slug}'")
    return instance


def _active_contract(client):
    contract = billing.active_contract(client)
    if contract is None:
        raise MCPToolError(f"Client '{client.name}' has no active hour package")
    return contract


def _project_member(issue, member):
    """Who spent the time: an active member (not a guest) of the work item's project."""
    members = ProjectMember.objects.filter(project_id=issue.project_id, is_active=True, role__gte=15).select_related(
        "member"
    )
    if _is_uuid(member):
        row = members.filter(member_id=member).first()
    else:
        row = members.filter(member__email__iexact=str(member or "").strip()).first()
    if row is None:
        raise MCPToolError(f"'{member}' is not an active member of project '{issue.project.identifier}'")
    return row.member


def _time_payload(issue):
    data = billing_views._issue_time_payload(issue)  # includes the client (by label or project)
    data["work_item"] = _issue_identifier(issue)
    data["total"] = billing.format_minutes(data["total_minutes"])
    return data


# ---------------------------------------------------------------------------
# Time spent and work kind
# ---------------------------------------------------------------------------


@register_tool(
    name="get_work_item_time",
    description=(
        "Time spent on a work item: entries, total, work kind (evolution, maintenance, internal), the approved "
        "estimate and how many hours were debited from the client's package."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="time",
)
def get_work_item_time(workspace_slug, work_item):
    return _time_payload(_get_issue(workspace_slug, work_item))


@register_tool(
    name="log_work_item_time",
    description=(
        "Record time someone spent on a work item. duration accepts '1h30', '90m', '1,5h', '45min' "
        "(up to 24h per entry). logged_on defaults to today and cannot be in the future."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "member": {"type": "string", "description": "E-mail or UUID of the person who did the work"},
            "duration": {"type": "string"},
            "logged_on": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
            "description": {"type": "string", "description": "What was done"},
        },
        ["workspace_slug", "work_item", "member", "duration"],
    ),
    category="time",
)
def log_work_item_time(workspace_slug, work_item, member, duration, logged_on=None, description=""):
    issue = _get_issue(workspace_slug, work_item)
    user = _project_member(issue, member)
    minutes = billing.parse_duration(duration)
    if not minutes or minutes > 24 * 60:
        raise MCPToolError("Invalid duration: use e.g. '1h30' or '45min' (up to 24h per entry)")
    day = _parse_date(logged_on, "logged_on") or billing.today()
    if day > billing.today():
        raise MCPToolError("'logged_on' cannot be in the future")
    entry = IssueWorkLog(
        issue=issue,
        project_id=issue.project_id,
        member=user,
        minutes=minutes,
        logged_on=day,
        description=(description or "").strip()[:2000],
    )
    entry.save(created_by_id=_mcp_actor().id)
    return {"logged": {"id": str(entry.id), "minutes": minutes}, **_time_payload(issue)}


def _work_log(issue, entry_id):
    entry = IssueWorkLog.objects.filter(issue=issue, pk=entry_id).first() if _is_uuid(entry_id) else None
    if entry is None:
        raise MCPToolError(f"Time entry '{entry_id}' does not exist on {_issue_identifier(issue)}")
    return entry


@register_tool(
    name="update_work_item_time",
    description="Correct a time entry (duration, date or description).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "entry_id": {"type": "string"},
            "duration": {"type": "string"},
            "logged_on": {"type": "string"},
            "description": {"type": "string"},
        },
        ["workspace_slug", "work_item", "entry_id"],
    ),
    category="time",
)
def update_work_item_time(workspace_slug, work_item, entry_id, duration=None, logged_on=None, description=None):
    issue = _get_issue(workspace_slug, work_item)
    entry = _work_log(issue, entry_id)
    if duration is not None:
        minutes = billing.parse_duration(duration)
        if not minutes or minutes > 24 * 60:
            raise MCPToolError("Invalid duration: use e.g. '1h30' or '45min' (up to 24h per entry)")
        entry.minutes = minutes
    if logged_on is not None:
        day = _parse_date(logged_on, "logged_on")
        if day is None or day > billing.today():
            raise MCPToolError("'logged_on' must be a past or current date")
        entry.logged_on = day
    if description is not None:
        entry.description = description.strip()[:2000]
    entry.save()
    return _time_payload(issue)


@register_tool(
    name="delete_work_item_time",
    description="Delete a time entry.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "entry_id": {"type": "string"}},
        ["workspace_slug", "work_item", "entry_id"],
    ),
    category="time",
)
def delete_work_item_time(workspace_slug, work_item, entry_id):
    issue = _get_issue(workspace_slug, work_item)
    _work_log(issue, entry_id).delete()
    return _time_payload(issue)


@register_tool(
    name="set_work_item_kind",
    description=(
        "Classify a work item: evolution (debits the client's package when its estimate is approved), "
        "maintenance or internal (counted, never debited). Changing the kind of an item with an approved "
        "estimate reverses or redoes the debit automatically."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "kind": {"type": "string", "enum": WORK_KINDS}},
        ["workspace_slug", "work_item", "kind"],
    ),
    category="time",
)
def set_work_item_kind(workspace_slug, work_item, kind):
    if kind not in WORK_KINDS:
        raise MCPToolError(f"kind must be one of {', '.join(WORK_KINDS)}")
    issue = _get_issue(workspace_slug, work_item)
    if billing.work_kind(issue) != kind:
        billing.change_work_kind(issue, kind, reason=VIA_MCP)
    return _time_payload(issue)


@register_tool(
    name="time_report",
    description=(
        "Hours spent in a period, for a project or a client (or the whole workspace), grouped by member, work "
        "item, kind or day. Dates default to the current month."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_CLIENT_PROPERTY,
            "from_date": {"type": "string", "description": "ISO date, inclusive"},
            "to_date": {"type": "string", "description": "ISO date, inclusive"},
            "group_by": {"type": "string", "enum": ["member", "work_item", "kind", "day"], "default": "member"},
        },
        ["workspace_slug"],
    ),
    category="time",
)
def time_report(workspace_slug, project=None, client=None, from_date=None, to_date=None, group_by="member"):
    workspace = _get_workspace(workspace_slug)
    start = _parse_date(from_date, "from_date") or billing.month_start(billing.today())
    end = _parse_date(to_date, "to_date") or billing.today()
    if end < start:
        raise MCPToolError("'to_date' must be after 'from_date'")
    logs = IssueWorkLog.objects.filter(workspace=workspace, logged_on__gte=start, logged_on__lte=end)
    scope = {"workspace": workspace.slug}
    if project:
        project_instance = _get_project(workspace_slug, project)
        logs = logs.filter(project=project_instance)
        scope["project"] = project_instance.identifier
    if client:
        client_instance = _get_client(workspace_slug, client)
        logs = logs.filter(issue__in=billing.client_issues(client_instance))
        scope["client"] = client_instance.name
    fields = {
        "member": ("member__email", "member__display_name"),
        "work_item": ("issue__project__identifier", "issue__sequence_id", "issue__name"),
        "kind": ("issue__work_kind__kind",),
        "day": ("logged_on",),
    }.get(group_by)
    if fields is None:
        raise MCPToolError("group_by must be member, work_item, kind or day")
    rows = logs.values(*fields).annotate(minutes=Sum("minutes")).order_by("-minutes")
    groups = []
    for row in rows:
        if group_by == "member":
            key = row["member__display_name"] or row["member__email"]
        elif group_by == "work_item":
            key = f"{row['issue__project__identifier']}-{row['issue__sequence_id']} {row['issue__name']}"
        elif group_by == "kind":
            key = row["issue__work_kind__kind"] or "unclassified"
        else:
            key = row["logged_on"].isoformat()
        groups.append({"key": key, "minutes": row["minutes"], "hours": str(billing.hours_of(row["minutes"]))})
    total = sum(group["minutes"] for group in groups)
    return {
        **scope,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "group_by": group_by,
        "total_minutes": total,
        "total_hours": str(billing.hours_of(total)),
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# Clients and contacts
# ---------------------------------------------------------------------------


@register_tool(
    name="list_clients",
    description="Clients of the workspace with their hour package balance and projects.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            "search": {"type": "string", "description": "Part of the name or the CNPJ/CPF"},
            "include_inactive": {"type": "boolean", "default": False},
        },
        ["workspace_slug"],
    ),
    category="clients",
)
def list_clients(workspace_slug, search=None, include_inactive=False):
    workspace = _get_workspace(workspace_slug)
    clients = Client.objects.filter(workspace=workspace)
    if not include_inactive:
        clients = clients.filter(is_active=True)
    if search:
        clients = clients.filter(
            Q(name__icontains=search) | Q(legal_name__icontains=search) | Q(document__icontains=search)
        )
    return {"clients": [billing_views._client(client) for client in clients.order_by("name")]}


@register_tool(
    name="retrieve_client",
    description=(
        "A client: package balance (lots and expiries), contacts, contracts, projects and maintenance hours "
        "of the month."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_CLIENT_PROPERTY}, ["workspace_slug", "client"]),
    category="clients",
)
def retrieve_client(workspace_slug, client):
    return billing_views._client(_get_client(workspace_slug, client), detail=True)


@register_tool(
    name="create_client",
    description="Register a client.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            "name": {"type": "string"},
            "legal_name": {"type": "string"},
            "document": {"type": "string", "description": "CNPJ or CPF"},
            "notes": {"type": "string"},
        },
        ["workspace_slug", "name"],
    ),
    category="clients",
)
def create_client(workspace_slug, name, legal_name="", document="", notes=""):
    workspace = _get_workspace(workspace_slug)
    name = (name or "").strip()
    if not name:
        raise MCPToolError("'name' is required")
    if Client.objects.filter(workspace=workspace, name__iexact=name).exists():
        raise MCPToolError(f"A client named '{name}' already exists")
    client = Client(
        workspace=workspace,
        name=name[:255],
        legal_name=(legal_name or "")[:255],
        document=(document or "")[:32],
        notes=notes or "",
    )
    client.save(created_by_id=_mcp_actor().id)
    return billing_views._client(client, detail=True)


@register_tool(
    name="update_client",
    description="Change a client's data, or deactivate/reactivate it.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "name": {"type": "string"},
            "legal_name": {"type": "string"},
            "document": {"type": "string"},
            "notes": {"type": "string"},
            "is_active": {"type": "boolean"},
        },
        ["workspace_slug", "client"],
    ),
    category="clients",
)
def update_client(workspace_slug, client, name=None, legal_name=None, document=None, notes=None, is_active=None):
    instance = _get_client(workspace_slug, client)
    if name is not None:
        if not name.strip():
            raise MCPToolError("'name' cannot be empty")
        instance.name = name.strip()[:255]
    if legal_name is not None:
        instance.legal_name = legal_name[:255]
    if document is not None:
        instance.document = document[:32]
    if notes is not None:
        instance.notes = notes
    if is_active is not None:
        instance.is_active = bool(is_active)
    instance.save()
    return billing_views._client(instance, detail=True)


@register_tool(
    name="add_client_contact",
    description=(
        "Add a contact to a client. can_approve=true lets them approve estimates on the request portal "
        "(approving debits the package)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "role": {"type": "string", "description": "Job title"},
            "can_approve": {"type": "boolean", "default": False},
        },
        ["workspace_slug", "client", "name"],
    ),
    category="clients",
)
def add_client_contact(workspace_slug, client, name, email="", phone="", role="", can_approve=False):
    instance = _get_client(workspace_slug, client)
    if not (name or "").strip():
        raise MCPToolError("'name' is required")
    email = (email or "").strip().lower()
    if email and ClientContact.objects.filter(client=instance, email__iexact=email).exists():
        raise MCPToolError(f"'{email}' is already a contact of this client")
    contact = ClientContact(
        workspace_id=instance.workspace_id,
        client=instance,
        name=name.strip()[:255],
        email=email,
        phone=(phone or "")[:64],
        role=(role or "")[:128],
        can_approve=bool(can_approve),
    )
    contact.save(created_by_id=_mcp_actor().id)
    return billing_views._contact(contact)


def _contact_of(instance, contact):
    contacts = ClientContact.objects.filter(client=instance)
    row = (
        contacts.filter(pk=contact).first()
        if _is_uuid(contact)
        else contacts.filter(Q(email__iexact=contact) | Q(name__iexact=contact)).first()
    )
    if row is None:
        raise MCPToolError(f"Contact '{contact}' does not exist for client '{instance.name}'")
    return row


@register_tool(
    name="update_client_contact",
    description="Change a client contact (including whether they can approve estimates).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "contact": {"type": "string", "description": "Contact UUID, e-mail or name"},
            "name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "role": {"type": "string"},
            "can_approve": {"type": "boolean"},
        },
        ["workspace_slug", "client", "contact"],
    ),
    category="clients",
)
def update_client_contact(
    workspace_slug, client, contact, name=None, email=None, phone=None, role=None, can_approve=None
):
    instance = _get_client(workspace_slug, client)
    row = _contact_of(instance, contact)
    if name is not None:
        if not name.strip():
            raise MCPToolError("'name' cannot be empty")
        row.name = name.strip()[:255]
    if email is not None:
        email = email.strip().lower()
        if email and ClientContact.objects.filter(client=instance, email__iexact=email).exclude(pk=row.pk).exists():
            raise MCPToolError(f"'{email}' is already a contact of this client")
        row.email = email
    if phone is not None:
        row.phone = phone[:64]
    if role is not None:
        row.role = role[:128]
    if can_approve is not None:
        row.can_approve = bool(can_approve)
    row.save()
    return billing_views._contact(row)


@register_tool(
    name="remove_client_contact",
    description="Remove a client contact.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_CLIENT_PROPERTY, "contact": {"type": "string"}},
        ["workspace_slug", "client", "contact"],
    ),
    category="clients",
)
def remove_client_contact(workspace_slug, client, contact):
    row = _contact_of(_get_client(workspace_slug, client), contact)
    name = row.name
    row.delete()
    return {"removed": name}


@register_tool(
    name="set_client_projects",
    description="Set which projects belong to a client (replaces the list; a project belongs to one client only).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "projects": {"type": "array", "items": {"type": "string"}, "description": "Project identifiers or UUIDs"},
        },
        ["workspace_slug", "client", "projects"],
    ),
    category="clients",
)
def set_client_projects(workspace_slug, client, projects):
    instance = _get_client(workspace_slug, client)
    if not isinstance(projects, list):
        raise MCPToolError("'projects' must be a list")
    project_ids = [str(_get_project(workspace_slug, project).id) for project in projects]
    error = billing_views.set_client_projects(instance, project_ids)
    if error:
        raise MCPToolError(error)
    return billing_views._client(instance, detail=True)


def _resolve_label(workspace_slug, ref):
    """A label by UUID or as 'PROJECT/Label name' (e.g. 'MAN/RastroPOP')."""
    from plane.db.models import Label

    labels = Label.objects.filter(workspace__slug=workspace_slug, project__isnull=False)
    if _is_uuid(ref):
        label = labels.filter(pk=ref).first()
    else:
        project_ref, _, name = str(ref or "").partition("/")
        if not name:
            raise MCPToolError(f"Label '{ref}': use 'PROJECT/Label name', e.g. 'MAN/RastroPOP', or the label UUID")
        project = _get_project(workspace_slug, project_ref)
        label = labels.filter(project=project, name__iexact=name.strip()).first()
    if label is None:
        raise MCPToolError(f"Label '{ref}' does not exist")
    return label


@register_tool(
    name="set_client_labels",
    description=(
        "Set the labels that identify a client on boards shared by several clients (e.g. 'MAN/RastroPOP'). "
        "Work items with the label belong to the client (the label wins over the project's client); requests "
        "from the client's registered contacts arrive with the label. Replaces the list; a label belongs to one "
        "client only."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "labels": {"type": "array", "items": {"type": "string"}, "description": "'PROJECT/Label' or label UUIDs"},
        },
        ["workspace_slug", "client", "labels"],
    ),
    category="clients",
)
def set_client_labels(workspace_slug, client, labels):
    instance = _get_client(workspace_slug, client)
    if not isinstance(labels, list):
        raise MCPToolError("'labels' must be a list")
    label_ids = [str(_resolve_label(workspace_slug, ref).id) for ref in labels]
    error = billing_views.set_client_labels(instance, label_ids)
    if error:
        raise MCPToolError(error)
    return billing_views._client(instance, detail=True)


# ---------------------------------------------------------------------------
# Hour packages and statement
# ---------------------------------------------------------------------------


@register_tool(
    name="create_client_contract",
    description=(
        "Create the client's hour package. It replaces the active one: what is left moves to the new package "
        "with its original expiry, and the current month is not credited twice. opening_balance brings hours "
        "the client already had when registering the package now."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "name": {"type": "string", "description": "e.g. 'Pacote 20h'"},
            "hours_per_month": {"type": "string"},
            "accumulation_months": {
                "type": "integer",
                "description": "How many months each monthly credit stays usable (1 to 24; 3 = quarter, 12 = year)",
            },
            "credit_day": {"type": "integer", "description": "Day of the month the credit lands (1 to 28)"},
            "starts_on": {"type": "string", "description": "ISO date"},
            "ends_on": {"type": "string", "description": "ISO date (optional)"},
            "low_balance_percent": {"type": "integer", "description": "Warn in the chat under this % (default 20)"},
            "opening_balance": {"type": "string", "description": "Hours already available today (optional)"},
        },
        ["workspace_slug", "client", "name", "hours_per_month", "accumulation_months", "starts_on"],
    ),
    category="clients",
)
def create_client_contract(
    workspace_slug,
    client,
    name,
    hours_per_month,
    accumulation_months,
    starts_on,
    credit_day=1,
    ends_on=None,
    low_balance_percent=20,
    opening_balance=None,
):
    instance = _get_client(workspace_slug, client)
    data = {
        "name": name,
        "hours_per_month": hours_per_month,
        "accumulation_months": accumulation_months,
        "credit_day": credit_day,
        "starts_on": starts_on,
        "low_balance_percent": low_balance_percent,
        "opening_balance": opening_balance,
    }
    if ends_on:
        data["ends_on"] = ends_on
    contract, error = billing_views.create_contract(instance, data)
    if error:
        raise MCPToolError(error)
    return {"contract": billing_views._contract(contract), "package": billing.package_summary(contract)}


@register_tool(
    name="update_client_contract",
    description=(
        "Change the active package (name, hours per month, accumulation, credit day, end date, warning %) "
        "or end it with is_active=false (what is left expires). Changes apply to future credits."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "name": {"type": "string"},
            "hours_per_month": {"type": "string"},
            "accumulation_months": {"type": "integer"},
            "credit_day": {"type": "integer"},
            "ends_on": {"type": "string"},
            "low_balance_percent": {"type": "integer"},
            "is_active": {"type": "boolean", "description": "false ends the package"},
        },
        ["workspace_slug", "client"],
    ),
    category="clients",
)
def update_client_contract(
    workspace_slug,
    client,
    name=None,
    hours_per_month=None,
    accumulation_months=None,
    credit_day=None,
    ends_on=None,
    low_balance_percent=None,
    is_active=None,
):
    instance = _get_client(workspace_slug, client)
    contract = _active_contract(instance)
    changes = {
        "name": name,
        "hours_per_month": hours_per_month,
        "accumulation_months": accumulation_months,
        "credit_day": credit_day,
        "ends_on": ends_on,
        "low_balance_percent": low_balance_percent,
        "is_active": is_active,
    }
    data = {key: value for key, value in changes.items() if value is not None}
    if not data:
        raise MCPToolError("Nothing to change")
    contract, error = billing_views.update_contract(contract, data)
    if error:
        raise MCPToolError(error)
    return {"contract": billing_views._contract(contract)}


@register_tool(
    name="get_client_statement",
    description=(
        "The client's hour statement: credits, debits, expirations, reversals, adjustments and excess hours, "
        "each with the balance after it (newest first), plus the package summary."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "from_date": {"type": "string"},
            "to_date": {"type": "string"},
        },
        ["workspace_slug", "client"],
    ),
    category="clients",
)
def get_client_statement(workspace_slug, client, from_date=None, to_date=None):
    instance = _get_client(workspace_slug, client)
    contract = _active_contract(instance)
    billing.refresh_contract(contract)
    rows = billing.statement(contract, _parse_date(from_date, "from_date"), _parse_date(to_date, "to_date"))
    entries = [billing_views._ledger_entry(entry, running) for entry, running in rows]
    return {
        "client": instance.name,
        "package": billing.package_summary(contract),
        "entries": entries,
    }


@register_tool(
    name="adjust_client_hours",
    description=(
        "Manual adjustment of the package balance: positive hours add a lot (valid like a monthly credit), "
        "negative hours consume the lots that expire first. A note explaining why is required."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "hours": {"type": "string", "description": "e.g. '4' or '-2,5'"},
            "note": {"type": "string"},
        },
        ["workspace_slug", "client", "hours", "note"],
    ),
    category="clients",
)
def adjust_client_hours(workspace_slug, client, hours, note):
    instance = _get_client(workspace_slug, client)
    contract = _active_contract(instance)
    amount = billing.parse_hours(hours, allow_negative=True)
    if amount is None:
        raise MCPToolError("Invalid hours: positive or negative, non zero, up to 9999")
    note = (note or "").strip()[:1900]
    if not note:
        raise MCPToolError("A note explaining the adjustment is required")
    billing.refresh_contract(contract)
    try:
        billing.adjust(contract, amount, note + VIA_MCP)
    except ValueError:
        raise MCPToolError(f"Insufficient balance: the package has {billing.balance(contract)}h available")
    return billing.package_summary(contract)


@register_tool(
    name="reverse_client_debit",
    description="Give back the hours of a debit (an approved estimate) to the lots it used. A debit is reversed once.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "entry_id": {"type": "string", "description": "Statement entry UUID of the debit"},
            "note": {"type": "string"},
        },
        ["workspace_slug", "client", "entry_id"],
    ),
    category="clients",
)
def reverse_client_debit(workspace_slug, client, entry_id, note=""):
    instance = _get_client(workspace_slug, client)
    debit = (
        HourLedgerEntry.objects.filter(contract__client=instance, pk=entry_id, kind=HourLedgerEntry.DEBIT).first()
        if _is_uuid(entry_id)
        else None
    )
    if debit is None:
        raise MCPToolError(f"Debit '{entry_id}' does not exist for client '{instance.name}'")
    if billing.reverse_debit(debit, note=((note or "").strip()[:1900] or "Estorno do débito") + VIA_MCP) is None:
        raise MCPToolError("This debit was already reversed")
    return billing.package_summary(debit.contract)


# ---------------------------------------------------------------------------
# Timeline (CRM)
# ---------------------------------------------------------------------------


@register_tool(
    name="get_client_timeline",
    description=(
        "The client's timeline, newest first: notes (meetings, calls, e-mails), requests and estimates from the "
        "portal, hour movements, deliveries and merged pull requests. types filters: "
        + ", ".join(TIMELINE_TYPES)
        + ". Use next_before to page."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "types": {"type": "array", "items": {"type": "string", "enum": list(TIMELINE_TYPES)}},
            "before": {"type": "string", "description": "next_before from the previous page"},
            "limit": {"type": "integer", "default": 40},
        },
        ["workspace_slug", "client"],
    ),
    category="clients",
)
def get_client_timeline(workspace_slug, client, types=None, before=None, limit=40):
    instance = _get_client(workspace_slug, client)
    contract = billing.active_contract(instance)
    if contract is not None:
        billing.refresh_contract(contract)
    types = [t for t in (types or []) if t in TIMELINE_TYPES] or None
    try:
        return build_timeline(instance, types, before, max(5, min(int(limit or 40), 100)))
    except ValueError:
        raise MCPToolError("Invalid 'before' cursor")


@register_tool(
    name="add_client_note",
    description="Record a meeting, call, e-mail or note on the client's timeline.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "kind": {"type": "string", "enum": NOTE_KINDS},
            "body": {"type": "string"},
            "occurred_at": {
                "type": "string",
                "description": "ISO date-time (Brasília time when no offset); default now",
            },
            "contacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Contact e-mails, names or UUIDs",
            },
        },
        ["workspace_slug", "client", "kind", "body"],
    ),
    category="clients",
)
def add_client_note(workspace_slug, client, kind, body, occurred_at=None, contacts=None):
    instance = _get_client(workspace_slug, client)
    if kind not in NOTE_KINDS:
        raise MCPToolError(f"kind must be one of {', '.join(NOTE_KINDS)}")
    body = (body or "").strip()
    if not body:
        raise MCPToolError("'body' is required")
    when = timezone.now()
    if occurred_at:
        try:
            when = datetime.datetime.fromisoformat(occurred_at)
        except ValueError:
            raise MCPToolError("'occurred_at' must be an ISO date-time")
        if timezone.is_naive(when):
            when = timezone.make_aware(when, billing.BILLING_TZ)
    contact_ids = [str(_contact_of(instance, contact).id) for contact in contacts or []]
    note = ClientTimelineNote(
        client=instance,
        workspace_id=instance.workspace_id,
        kind=kind,
        occurred_at=when,
        body=body[:5000],
        contact_ids=contact_ids,
    )
    note.save(created_by_id=_mcp_actor().id)
    return {"id": str(note.id), "client": instance.name, "kind": kind, "occurred_at": when.isoformat()}


# ---------------------------------------------------------------------------
# Development (GitHub)
# ---------------------------------------------------------------------------


@register_tool(
    name="get_work_item_development",
    description="Branches, commits and pull requests linked to a work item, and the suggested branch name.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="development",
)
def get_work_item_development(workspace_slug, work_item):
    from plane.utils.conjo_github import branch_name_for

    issue = _get_issue(workspace_slug, work_item)
    grouped = {"branches": [], "commits": [], "pull_requests": []}
    group_for = {"branch": "branches", "commit": "commits", "pull_request": "pull_requests"}
    for link in IssueDevelopmentLink.objects.filter(issue=issue).order_by("-event_at"):
        grouped[group_for.get(link.kind, "commits")].append(
            {
                "repository": link.repository,
                "id": link.external_id,
                "title": link.title,
                "url": link.url,
                "state": link.state,
                "author": link.author_login or link.author_name,
                "at": link.event_at.isoformat() if link.event_at else None,
            }
        )
    return {
        "work_item": _issue_identifier(issue),
        "branch_name": branch_name_for(issue.project.identifier, issue.sequence_id, issue.name),
        **grouped,
    }
