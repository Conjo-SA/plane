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
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
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
    _CONFIRM_PROPERTY,
    _PROJECT_PROPERTY,
    _WORK_ITEM_PROPERTY,
    _WORKSPACE_SLUG_PROPERTY,
    MAX_LIST_ITEMS,
    MAX_NAME_LENGTH,
    ROLE_MEMBER,
    MCPToolError,
    _clean_text,
    _date_property,
    _get_issue,
    _get_project,
    _get_workspace,
    _is_uuid,
    _issue_identifier,
    _limit,
    _limit_property,
    _mcp_actor,
    _name_property,
    _parse_date,
    _require_confirm,
    _text_property,
    _uuid_list_property,
)
from plane.mcp.tools.registry import register_tool
from plane.utils import conjo_billing as billing
from plane.utils.conjo_timeline import TYPES as TIMELINE_TYPES
from plane.utils.conjo_timeline import build_timeline

WORK_KINDS = [kind for kind, _ in IssueWorkKind.KIND_CHOICES]
NOTE_KINDS = [kind for kind, _ in ClientTimelineNote.KIND_CHOICES]
VIA_MCP = " (via MCP)"
MAX_NOTE_LENGTH = 5000
MAX_LEDGER_NOTE_LENGTH = 1900

_CLIENT_PROPERTY = {"client": {"type": "string", "maxLength": 255, "description": "UUID, nome ou CNPJ/CPF do cliente"}}
_HOURS = ["string", "number"]


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _get_client(workspace_slug, client):
    workspace = _get_workspace(workspace_slug)
    clients = Client.objects.filter(workspace=workspace)
    value = str(client or "").strip()
    if not value:
        raise MCPToolError("'client' é obrigatório")
    if _is_uuid(value):
        instance = clients.filter(pk=value).first()
    else:
        instance = clients.filter(Q(name__iexact=value) | Q(legal_name__iexact=value) | Q(document=value)).first()
    if instance is None:
        raise MCPToolError(f"O cliente '{client}' não existe no workspace '{workspace_slug}'")
    return instance


def _active_contract(client):
    contract = billing.active_contract(client)
    if contract is None:
        raise MCPToolError(f"O cliente '{client.name}' não tem pacote de horas ativo")
    return contract


def _project_member(issue, member):
    """Who spent the time: an active member (not a guest) of the work item's project."""
    members = ProjectMember.objects.filter(
        project_id=issue.project_id, is_active=True, role__gte=ROLE_MEMBER
    ).select_related("member")
    if _is_uuid(member):
        row = members.filter(member_id=member).first()
    else:
        row = members.filter(member__email__iexact=str(member or "").strip()).first()
    if row is None:
        raise MCPToolError(f"'{member}' não é membro ativo (member) do projeto '{issue.project.identifier}'")
    return row.member


def _clean_email(value, field="email"):
    email = str(value or "").strip().lower()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        raise MCPToolError(f"'{field}' não é um e-mail válido")
    return email


def _time_payload(issue):
    data = billing_views._issue_time_payload(issue)  # includes the client (by label or project)
    data["work_item"] = _issue_identifier(issue)
    data["total"] = billing.format_minutes(data["total_minutes"])
    return data


# ---------------------------------------------------------------------------
# Time spent and work kind
# ---------------------------------------------------------------------------

_ENTRY_ID = {"entry_id": {"type": "string", "maxLength": 100, "description": "UUID do lançamento (get_work_item_time)"}}
_DURATION = {"type": "string", "maxLength": 20, "description": "Duração: '1h30', '90m', '1,5h' ou '45min' (até 24h)"}


@register_tool(
    name="get_work_item_time",
    description=(
        "Tempo gasto num item: lançamentos, total, tipo de trabalho (evolution, maintenance, internal), o "
        "orçamento aprovado e quantas horas foram debitadas do pacote do cliente."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="time",
)
def get_work_item_time(workspace_slug, work_item):
    return _time_payload(_get_issue(workspace_slug, work_item))


@register_tool(
    name="log_work_item_time",
    description=(
        "Lança o tempo que alguém gastou num item. A pessoa precisa ser membro (não convidado) do projeto. "
        "logged_on padrão é hoje e não pode ser no futuro. description (o que foi feito) é obrigatória. Lançar "
        "horas não debita o pacote do cliente (o débito vem do orçamento aprovado)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "member": {"type": "string", "maxLength": 254, "description": "E-mail ou UUID de quem fez o trabalho"},
            "duration": _DURATION,
            "logged_on": _date_property("Dia do trabalho ISO (AAAA-MM-DD)"),
            "description": {**_text_property("O que foi feito (obrigatório)", 2000), "minLength": 1},
        },
        ["workspace_slug", "work_item", "member", "duration", "description"],
    ),
    category="time",
)
def log_work_item_time(workspace_slug, work_item, member, duration, logged_on=None, description=None):
    description = _work_log_description(description)
    issue = _get_issue(workspace_slug, work_item)
    user = _project_member(issue, member)
    minutes = billing.parse_duration(duration)
    if not minutes or minutes > 24 * 60:
        raise MCPToolError("'duration' inválida: use ex.: '1h30' ou '45min' (até 24h por lançamento)")
    day = _parse_date(logged_on, "logged_on") or billing.today()
    if day > billing.today():
        raise MCPToolError("'logged_on' não pode ser no futuro")
    entry = IssueWorkLog(
        issue=issue,
        project_id=issue.project_id,
        member=user,
        minutes=minutes,
        logged_on=day,
        description=description,
    )
    entry.save(created_by_id=_mcp_actor().id)
    return {"logged": {"id": str(entry.id), "minutes": minutes}, **_time_payload(issue)}


def _work_log_description(value):
    """Manual entries always say what was done (commit entries are described by the commit itself)."""
    text = _clean_text(value, "description", 2000)
    if not text:
        raise MCPToolError("'description' é obrigatória: descreva o que foi feito")
    return text


def _work_log(issue, entry_id):
    entry = IssueWorkLog.objects.filter(issue=issue, pk=entry_id).first() if _is_uuid(entry_id) else None
    if entry is None:
        raise MCPToolError(f"O lançamento '{entry_id}' não existe em {_issue_identifier(issue)}")
    return entry


@register_tool(
    name="update_work_item_time",
    description=(
        "Corrige um lançamento de horas (duração, dia ou descrição). A descrição não pode ficar vazia em "
        "lançamentos manuais: um lançamento antigo sem descrição só é salvo se a correção trouxer description."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            **_ENTRY_ID,
            "duration": _DURATION,
            "logged_on": _date_property("Dia do trabalho ISO (AAAA-MM-DD)"),
            "description": {**_text_property("O que foi feito (não pode ficar vazio)", 2000), "minLength": 1},
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
            raise MCPToolError("'duration' inválida: use ex.: '1h30' ou '45min' (até 24h por lançamento)")
        entry.minutes = minutes
    if logged_on is not None:
        day = _parse_date(logged_on, "logged_on")
        if day is None or day > billing.today():
            raise MCPToolError("'logged_on' deve ser hoje ou uma data passada")
        entry.logged_on = day
    if description is not None:
        entry.description = _clean_text(description, "description", 2000)
    if entry.source == IssueWorkLog.SOURCE_MANUAL and not entry.description:
        raise MCPToolError("'description' é obrigatória: descreva o que foi feito")
    entry.save()
    return _time_payload(issue)


@register_tool(
    name="delete_work_item_time",
    description="Exclui um lançamento de horas.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, **_ENTRY_ID},
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
        "Classifica um item: evolution (debita o pacote do cliente quando o orçamento é aprovado), maintenance "
        "ou internal (contadas, nunca debitadas). Mudar o tipo de um item com orçamento aprovado estorna ou "
        "refaz o débito automaticamente (aparece no extrato do cliente)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "kind": {"type": "string", "enum": WORK_KINDS, "description": "Tipo de trabalho"},
        },
        ["workspace_slug", "work_item", "kind"],
    ),
    category="time",
)
def set_work_item_kind(workspace_slug, work_item, kind):
    if kind not in WORK_KINDS:
        raise MCPToolError(f"'kind' deve ser um destes: {', '.join(WORK_KINDS)}")
    issue = _get_issue(workspace_slug, work_item)
    if billing.work_kind(issue) != kind:
        billing.change_work_kind(issue, kind, reason=VIA_MCP)
    return _time_payload(issue)


@register_tool(
    name="time_report",
    description=(
        "Horas lançadas num período, de um projeto, de um cliente ou do workspace inteiro, agrupadas por membro, "
        "item, tipo ou dia. As datas padrão são o mês corrente."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_CLIENT_PROPERTY,
            "from_date": _date_property("Início ISO, inclusive"),
            "to_date": _date_property("Fim ISO, inclusive"),
            "group_by": {
                "type": "string",
                "enum": ["member", "work_item", "kind", "day"],
                "default": "member",
                "description": "Agrupamento (padrão member)",
            },
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
        raise MCPToolError("'to_date' deve ser depois de 'from_date'")
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
        raise MCPToolError("'group_by' deve ser member, work_item, kind ou day")
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
    description="Clientes do workspace com saldo do pacote de horas e projetos.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            "search": {"type": "string", "maxLength": 255, "description": "Parte do nome ou do CNPJ/CPF"},
            "include_inactive": {"type": "boolean", "default": False, "description": "Inclui clientes inativos"},
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
        "Um cliente completo: saldo do pacote (lotes e vencimentos), contatos (com quem pode aprovar "
        "orçamentos), histórico de contratos, projetos, etiquetas e horas de manutenção do mês."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_CLIENT_PROPERTY}, ["workspace_slug", "client"]),
    category="clients",
)
def retrieve_client(workspace_slug, client):
    return billing_views._client(_get_client(workspace_slug, client), detail=True)


_CLIENT_FIELDS = {
    "legal_name": _name_property("Razão social"),
    "document": {"type": "string", "maxLength": 32, "description": "CNPJ ou CPF"},
    "notes": _text_property("Observações internas (texto simples)"),
}


@register_tool(
    name="create_client",
    description="Cadastra um cliente.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, "name": _name_property("Nome do cliente"), **_CLIENT_FIELDS},
        ["workspace_slug", "name"],
    ),
    category="clients",
)
def create_client(workspace_slug, name, legal_name="", document="", notes=""):
    workspace = _get_workspace(workspace_slug)
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if Client.objects.filter(workspace=workspace, name__iexact=name).exists():
        raise MCPToolError(f"Já existe um cliente chamado '{name}'")
    client = Client(
        workspace=workspace,
        name=name,
        legal_name=_clean_text(legal_name, "legal_name", MAX_NAME_LENGTH),
        document=_clean_text(document, "document", 32),
        notes=_clean_text(notes, "notes"),
    )
    client.save(created_by_id=_mcp_actor().id)
    return billing_views._client(client, detail=True)


@register_tool(
    name="update_client",
    description=(
        "Altera os dados de um cliente, ou o desativa/reativa (cliente inativo não pode ser escolhido em itens novos)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "name": _name_property("Novo nome"),
            **_CLIENT_FIELDS,
            "is_active": {"type": "boolean", "description": "false desativa, true reativa"},
        },
        ["workspace_slug", "client"],
    ),
    category="clients",
)
def update_client(workspace_slug, client, name=None, legal_name=None, document=None, notes=None, is_active=None):
    instance = _get_client(workspace_slug, client)
    if name is not None:
        name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
        if (
            Client.objects.filter(workspace_id=instance.workspace_id, name__iexact=name)
            .exclude(pk=instance.pk)
            .exists()
        ):
            raise MCPToolError(f"Já existe um cliente chamado '{name}'")
        instance.name = name
    if legal_name is not None:
        instance.legal_name = _clean_text(legal_name, "legal_name", MAX_NAME_LENGTH)
    if document is not None:
        instance.document = _clean_text(document, "document", 32)
    if notes is not None:
        instance.notes = _clean_text(notes, "notes")
    if is_active is not None:
        instance.is_active = bool(is_active)
    instance.save()
    return billing_views._client(instance, detail=True)


_CONTACT_FIELDS = {
    "email": {"type": "string", "maxLength": 254, "description": "E-mail (é com ele que o contato entra no portal)"},
    "phone": {"type": "string", "maxLength": 64, "description": "Telefone"},
    "role": {"type": "string", "maxLength": 128, "description": "Cargo"},
    "can_approve": {
        "type": "boolean",
        "description": "true permite aprovar orçamentos no portal (aprovar debita o pacote do cliente)",
    },
}


@register_tool(
    name="add_client_contact",
    description=(
        "Adiciona um contato ao cliente. can_approve=true deixa a pessoa aprovar orçamentos no portal de "
        "chamados, o que debita horas do pacote: confira o e-mail."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_CLIENT_PROPERTY, "name": _name_property("Nome do contato"), **_CONTACT_FIELDS},
        ["workspace_slug", "client", "name"],
    ),
    category="clients",
)
def add_client_contact(workspace_slug, client, name, email="", phone="", role="", can_approve=False):
    instance = _get_client(workspace_slug, client)
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    email = _clean_email(email)
    if can_approve and not email:
        raise MCPToolError("Quem aprova orçamentos precisa de e-mail (é com ele que entra no portal)")
    if email and ClientContact.objects.filter(client=instance, email__iexact=email).exists():
        raise MCPToolError(f"'{email}' já é contato deste cliente")
    contact = ClientContact(
        workspace_id=instance.workspace_id,
        client=instance,
        name=name,
        email=email,
        phone=_clean_text(phone, "phone", 64),
        role=_clean_text(role, "role", 128),
        can_approve=bool(can_approve),
    )
    contact.save(created_by_id=_mcp_actor().id)
    return billing_views._contact(contact)


def _contact_of(instance, contact):
    contacts = ClientContact.objects.filter(client=instance)
    row = (
        contacts.filter(pk=contact).first()
        if _is_uuid(contact)
        else contacts.filter(Q(email__iexact=str(contact).strip()) | Q(name__iexact=str(contact).strip())).first()
    )
    if row is None:
        raise MCPToolError(f"O contato '{contact}' não existe no cliente '{instance.name}'")
    return row


_CONTACT_REF = {"contact": {"type": "string", "maxLength": 254, "description": "UUID, e-mail ou nome do contato"}}


@register_tool(
    name="update_client_contact",
    description="Altera um contato do cliente (inclusive se pode aprovar orçamentos no portal).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            **_CONTACT_REF,
            "name": _name_property("Novo nome"),
            **_CONTACT_FIELDS,
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
        row.name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if email is not None:
        email = _clean_email(email)
        if email and ClientContact.objects.filter(client=instance, email__iexact=email).exclude(pk=row.pk).exists():
            raise MCPToolError(f"'{email}' já é contato deste cliente")
        row.email = email
    if phone is not None:
        row.phone = _clean_text(phone, "phone", 64)
    if role is not None:
        row.role = _clean_text(role, "role", 128)
    if can_approve is not None:
        row.can_approve = bool(can_approve)
    if row.can_approve and not row.email:
        raise MCPToolError("Quem aprova orçamentos precisa de e-mail (é com ele que entra no portal)")
    row.save()
    return billing_views._contact(row)


@register_tool(
    name="remove_client_contact",
    description="Remove um contato do cliente (ele deixa de poder aprovar orçamentos no portal).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_CLIENT_PROPERTY, **_CONTACT_REF},
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
    description=(
        "Define quais projetos são do cliente (SUBSTITUI a lista; um projeto pertence a um cliente só). Os itens "
        "desses projetos passam a contar para o cliente; [] desliga todos."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "projects": _uuid_list_property("Identificadores ou UUIDs dos projetos"),
        },
        ["workspace_slug", "client", "projects"],
    ),
    category="clients",
)
def set_client_projects(workspace_slug, client, projects):
    instance = _get_client(workspace_slug, client)
    if not isinstance(projects, list):
        raise MCPToolError("'projects' deve ser uma lista")
    if len(projects) > MAX_LIST_ITEMS:
        raise MCPToolError(f"'projects' aceita no máximo {MAX_LIST_ITEMS} itens")
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
            raise MCPToolError(f"Etiqueta '{ref}': use 'PROJETO/Nome da etiqueta', ex.: 'MAN/RastroPOP', ou o UUID")
        project = _get_project(workspace_slug, project_ref)
        label = labels.filter(project=project, name__iexact=name.strip()).first()
    if label is None:
        raise MCPToolError(f"A etiqueta '{ref}' não existe")
    return label


@register_tool(
    name="set_client_labels",
    description=(
        "Define as etiquetas do cliente em boards compartilhados por vários clientes (ex.: 'MAN/RastroPOP'), "
        "sincronizadas com o cliente do item: escolher o cliente aplica a etiqueta, um link do portal com a tag "
        "da etiqueta define o cliente, e etiquetar um card sem cliente define o cliente (cards que já têm a "
        "etiqueta passam a ser do cliente). SUBSTITUI a lista; uma etiqueta pertence a um cliente só."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "labels": {
                "type": "array",
                "items": {"type": "string", "maxLength": 300},
                "maxItems": MAX_LIST_ITEMS,
                "description": "'PROJETO/Etiqueta' ou UUIDs das etiquetas",
            },
        },
        ["workspace_slug", "client", "labels"],
    ),
    category="clients",
)
def set_client_labels(workspace_slug, client, labels):
    instance = _get_client(workspace_slug, client)
    if not isinstance(labels, list):
        raise MCPToolError("'labels' deve ser uma lista")
    if len(labels) > MAX_LIST_ITEMS:
        raise MCPToolError(f"'labels' aceita no máximo {MAX_LIST_ITEMS} itens")
    label_ids = [str(_resolve_label(workspace_slug, ref).id) for ref in labels]
    error = billing_views.set_client_labels(instance, label_ids)
    if error:
        raise MCPToolError(error)
    return billing_views._client(instance, detail=True)


@register_tool(
    name="set_work_item_client",
    description=(
        "Escolhe o cliente de um item (a etiqueta do cliente é aplicada), ou limpa com client='' para voltar ao "
        "cliente do projeto. Mover um item com orçamento aprovado move as horas debitadas para o pacote do novo "
        "cliente (aparece nos extratos)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "client": {
                "type": "string",
                "maxLength": 255,
                "description": "UUID, nome ou CNPJ/CPF do cliente; '' limpa",
            },
        },
        ["workspace_slug", "work_item", "client"],
    ),
    category="clients",
)
def set_work_item_client(workspace_slug, work_item, client):
    issue = _get_issue(workspace_slug, work_item)
    instance = _get_client(workspace_slug, client) if str(client or "").strip() else None
    if instance is not None and not instance.is_active:
        raise MCPToolError(f"O cliente '{instance.name}' está inativo")
    billing.set_issue_client(issue, instance)
    current, via = billing.client_resolution(issue)
    return {
        "work_item": _issue_identifier(issue),
        "client": {"id": str(current.id), "name": current.name, "via": via} if current else None,
    }


# ---------------------------------------------------------------------------
# Hour packages and statement
# ---------------------------------------------------------------------------

_CONTRACT_FIELDS = {
    "name": _name_property("Nome do pacote, ex.: 'Pacote 20h'"),
    "hours_per_month": {"type": _HOURS, "maxLength": 10, "description": "Horas creditadas por mês, ex.: '20'"},
    "accumulation_months": {
        "type": "integer",
        "minimum": 1,
        "maximum": 24,
        "description": "Por quantos meses cada crédito mensal pode ser usado (1 a 24; 3 = trimestre, 12 = ano)",
    },
    "credit_day": {"type": "integer", "minimum": 1, "maximum": 28, "description": "Dia do mês do crédito (1 a 28)"},
    "ends_on": _date_property("Fim do contrato ISO (opcional)"),
    "low_balance_percent": {
        "type": "integer",
        "minimum": 0,
        "maximum": 100,
        "description": "Avisa no chat abaixo deste % de saldo (padrão 20)",
    },
}


@register_tool(
    name="create_client_contract",
    description=(
        "Cria o pacote de horas do cliente. Se já houver pacote ativo, ele é SUBSTITUÍDO (encerrado; o saldo "
        "passa para o novo com o vencimento original e o mês corrente não é creditado duas vezes) e é preciso "
        "confirm=true. opening_balance traz horas que o cliente já tinha ao cadastrar."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            **_CONTRACT_FIELDS,
            "starts_on": _date_property("Início ISO (AAAA-MM-DD)"),
            "opening_balance": {
                "type": _HOURS,
                "maxLength": 10,
                "description": "Horas já disponíveis hoje (opcional)",
            },
            "confirm": {"type": "boolean", "description": "Obrigatório (true) quando substitui um pacote ativo"},
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
    confirm=False,
):
    instance = _get_client(workspace_slug, client)
    current = billing.active_contract(instance)
    if current is not None:
        _require_confirm(confirm, f"O pacote ativo '{current.name}' será encerrado e substituído.")
    data = {
        "name": _clean_text(name, "name", MAX_NAME_LENGTH, required=True),
        "hours_per_month": str(hours_per_month),
        "accumulation_months": accumulation_months,
        "credit_day": credit_day,
        "starts_on": starts_on,
        "low_balance_percent": low_balance_percent,
        "opening_balance": str(opening_balance) if opening_balance is not None else None,
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
        "Altera o pacote ativo (nome, horas por mês, acúmulo, dia do crédito, fim, % de aviso); vale para os "
        "próximos créditos. is_active=false ENCERRA o pacote e o saldo restante expira (IRREVERSÍVEL, exige "
        "confirm=true)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            **_CONTRACT_FIELDS,
            "is_active": {"type": "boolean", "description": "false encerra o pacote (o saldo expira)"},
            "confirm": {"type": "boolean", "description": "Obrigatório (true) para encerrar o pacote"},
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
    confirm=False,
):
    instance = _get_client(workspace_slug, client)
    contract = _active_contract(instance)
    if is_active is False:
        _require_confirm(confirm, f"Encerrar o pacote '{contract.name}' faz o saldo restante expirar.")
    changes = {
        "name": _clean_text(name, "name", MAX_NAME_LENGTH, required=True) if name is not None else None,
        "hours_per_month": str(hours_per_month) if hours_per_month is not None else None,
        "accumulation_months": accumulation_months,
        "credit_day": credit_day,
        "ends_on": ends_on,
        "low_balance_percent": low_balance_percent,
        "is_active": is_active,
    }
    data = {key: value for key, value in changes.items() if value is not None}
    if not data:
        raise MCPToolError("Nada para alterar")
    contract, error = billing_views.update_contract(contract, data)
    if error:
        raise MCPToolError(error)
    return {"contract": billing_views._contract(contract)}


@register_tool(
    name="get_client_statement",
    description=(
        "Extrato de horas do cliente: créditos, débitos, vencimentos, estornos, ajustes e horas excedentes, "
        "cada um com o saldo depois dele (mais recente primeiro), mais o resumo do pacote."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "from_date": _date_property("Início ISO (opcional)"),
            "to_date": _date_property("Fim ISO (opcional)"),
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
        "Ajuste manual do saldo do pacote (aparece no extrato do cliente): horas positivas criam um lote "
        "(válido como um crédito mensal), negativas consomem os lotes que vencem primeiro. Nota explicando o "
        "motivo é obrigatória. Para desfazer, faça um ajuste contrário."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "hours": {"type": _HOURS, "maxLength": 10, "description": "Horas, ex.: '4' ou '-2,5'"},
            "note": _text_property("Motivo do ajuste (obrigatório)", MAX_LEDGER_NOTE_LENGTH),
        },
        ["workspace_slug", "client", "hours", "note"],
    ),
    category="clients",
)
def adjust_client_hours(workspace_slug, client, hours, note):
    instance = _get_client(workspace_slug, client)
    contract = _active_contract(instance)
    amount = billing.parse_hours(str(hours), allow_negative=True)
    if amount is None:
        raise MCPToolError("'hours' inválidas: positivas ou negativas, diferentes de zero, até 9999")
    note = _clean_text(note, "note", MAX_LEDGER_NOTE_LENGTH)
    if not note:
        raise MCPToolError("Uma nota explicando o ajuste (note) é obrigatória")
    billing.refresh_contract(contract)
    try:
        billing.adjust(contract, amount, note + VIA_MCP)
    except ValueError:
        raise MCPToolError(f"Saldo insuficiente: o pacote tem {billing.balance(contract)}h disponíveis")
    return billing.package_summary(contract)


@register_tool(
    name="reverse_client_debit",
    description=(
        "Estorna um débito (orçamento aprovado): devolve as horas aos lotes que ele usou e aparece no extrato. "
        "Cada débito só pode ser estornado uma vez (IRREVERSÍVEL); exige confirm=true."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "entry_id": {
                "type": "string",
                "maxLength": 100,
                "description": "UUID do lançamento de débito no extrato (get_client_statement)",
            },
            "note": _text_property("Motivo do estorno", MAX_LEDGER_NOTE_LENGTH),
            **_CONFIRM_PROPERTY,
        },
        ["workspace_slug", "client", "entry_id"],
    ),
    category="clients",
)
def reverse_client_debit(workspace_slug, client, entry_id, note="", confirm=False):
    instance = _get_client(workspace_slug, client)
    debit = (
        HourLedgerEntry.objects.filter(contract__client=instance, pk=entry_id, kind=HourLedgerEntry.DEBIT).first()
        if _is_uuid(entry_id)
        else None
    )
    if debit is None:
        raise MCPToolError(f"O débito '{entry_id}' não existe para o cliente '{instance.name}'")
    _require_confirm(confirm, "O estorno de um débito não pode ser desfeito.")
    note = _clean_text(note, "note", MAX_LEDGER_NOTE_LENGTH) or "Estorno do débito"
    if billing.reverse_debit(debit, note=note + VIA_MCP) is None:
        raise MCPToolError("Este débito já foi estornado")
    return billing.package_summary(debit.contract)


# ---------------------------------------------------------------------------
# Timeline (CRM)
# ---------------------------------------------------------------------------


@register_tool(
    name="get_client_timeline",
    description=(
        "Linha do tempo do cliente, mais recente primeiro: notas (reuniões, ligações, e-mails), pedidos e "
        "orçamentos do portal, movimentos de horas, entregas e pull requests mesclados. Filtro types: "
        + ", ".join(TIMELINE_TYPES)
        + ". Use next_before para paginar."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": list(TIMELINE_TYPES)},
                "maxItems": len(TIMELINE_TYPES),
                "description": "Tipos de evento a incluir",
            },
            "before": {"type": "string", "maxLength": 64, "description": "next_before da página anterior"},
            "limit": _limit_property(40, 100),
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
        return build_timeline(instance, types, before, max(5, _limit(limit, 40, 100)))
    except ValueError:
        raise MCPToolError("Cursor 'before' inválido")


@register_tool(
    name="add_client_note",
    description=(
        "Registra uma reunião, ligação, e-mail ou nota na linha do tempo do cliente (uso interno; o cliente não vê)."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "kind": {"type": "string", "enum": NOTE_KINDS, "description": "Tipo do registro"},
            "body": _text_property("Texto do registro (texto simples)", MAX_NOTE_LENGTH),
            "occurred_at": {
                "type": "string",
                "maxLength": 40,
                "description": "Data-hora ISO (horário de Brasília quando sem fuso); padrão agora",
            },
            "contacts": {
                "type": "array",
                "items": {"type": "string", "maxLength": 254},
                "maxItems": 50,
                "description": "E-mails, nomes ou UUIDs dos contatos envolvidos",
            },
        },
        ["workspace_slug", "client", "kind", "body"],
    ),
    category="clients",
)
def add_client_note(workspace_slug, client, kind, body, occurred_at=None, contacts=None):
    instance = _get_client(workspace_slug, client)
    if kind not in NOTE_KINDS:
        raise MCPToolError(f"'kind' deve ser um destes: {', '.join(NOTE_KINDS)}")
    body = _clean_text(body, "body", MAX_NOTE_LENGTH, required=True)
    when = timezone.now()
    if occurred_at:
        try:
            when = datetime.datetime.fromisoformat(str(occurred_at))
        except ValueError:
            raise MCPToolError("'occurred_at' deve ser uma data-hora ISO")
        if timezone.is_naive(when):
            when = timezone.make_aware(when, billing.BILLING_TZ)
    contact_ids = list(dict.fromkeys(str(_contact_of(instance, contact).id) for contact in contacts or []))
    note = ClientTimelineNote(
        client=instance,
        workspace_id=instance.workspace_id,
        kind=kind,
        occurred_at=when,
        body=body,
        contact_ids=contact_ids,
    )
    note.save(created_by_id=_mcp_actor().id)
    return {"id": str(note.id), "client": instance.name, "kind": kind, "occurred_at": when.isoformat()}


@register_tool(
    name="delete_client_note",
    description=(
        "Exclui um registro da linha do tempo do cliente. Só registros feitos pelo MCP; os das pessoas ficam."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_CLIENT_PROPERTY,
            "note_id": {"type": "string", "maxLength": 100, "description": "UUID do registro (get_client_timeline)"},
        },
        ["workspace_slug", "client", "note_id"],
    ),
    category="clients",
)
def delete_client_note(workspace_slug, client, note_id):
    instance = _get_client(workspace_slug, client)
    note = ClientTimelineNote.objects.filter(client=instance, pk=note_id).first() if _is_uuid(note_id) else None
    if note is None:
        raise MCPToolError(f"O registro '{note_id}' não existe na linha do tempo de '{instance.name}'")
    if note.created_by_id != _mcp_actor().id:
        raise MCPToolError("Só registros feitos pelo MCP podem ser excluídos por aqui")
    note.delete()
    return {"deleted": str(note_id)}


# ---------------------------------------------------------------------------
# Development (GitHub)
# ---------------------------------------------------------------------------


@register_tool(
    name="get_work_item_development",
    description="Branches, commits e pull requests ligados a um item, e o nome de branch sugerido.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="development",
)
def get_work_item_development(workspace_slug, work_item):
    from plane.utils.conjo_github import branch_name_for

    issue = _get_issue(workspace_slug, work_item)
    grouped = {"branches": [], "commits": [], "pull_requests": []}
    group_for = {"branch": "branches", "commit": "commits", "pull_request": "pull_requests"}
    for link in IssueDevelopmentLink.objects.filter(issue=issue).order_by("-event_at")[:200]:
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
