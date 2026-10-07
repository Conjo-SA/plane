# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the day-to-day operations the app does outside the board.

Requests on behalf of a client (Entrada), hour estimates sent to the client through the request
portal, attachments, estimate points, archiving projects and what the MCP token can do. Each tool
reuses the app's own functions so the rules stay in one place.
"""

# Django imports
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import FileAsset, Intake, IntakeIssue, IntakePortal, Issue, State
from plane.db.models.intake import SourceType
from plane.mcp.tools.handlers import (
    _PROJECT_PROPERTY,
    _WORK_ITEM_PROPERTY,
    _WORKSPACE_SLUG_PROPERTY,
    MAX_NAME_LENGTH,
    PRIORITY_CHOICES,
    MCPToolError,
    _clean_html,
    _clean_text,
    _get_issue,
    _get_project,
    _html_property,
    _issue_identifier,
    _issue_snapshot,
    _mcp_actor,
    _name_property,
    _record_activity,
    _serialize_issue,
    _serialize_project,
    _text_property,
)
from plane.mcp.tools.registry import register_tool
from plane.utils.intake_portal import (
    MAX_BUDGET_NOTE_LENGTH,
    request_portal_budget,
    serialize_budget_context,
    serialize_portal_budget,
)

# Signed download links handed to the operator are short lived.
ATTACHMENT_URL_EXPIRATION = 600


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _portal_ticket(issue):
    """The intake row of a ticket opened on the request portal (it has a requester who reads and approves)."""
    return (
        IntakeIssue.objects.filter(issue=issue, source=SourceType.PORTAL, source_email__isnull=False)
        .exclude(source_email="")
        .first()
    )


# ---------------------------------------------------------------------------
# Requests (Entrada)
# ---------------------------------------------------------------------------


@register_tool(
    name="create_intake_item",
    description=(
        "Abre um pedido na Entrada do projeto (fica na triagem, fora do board, até triage_intake_item aceitar), "
        "como o botão de novo pedido do app. client define o cliente do pedido. requester_email (precisa ser "
        "contato cadastrado do cliente e o portal do projeto estar ligado) transforma o pedido em CHAMADO DO "
        "PORTAL: o contato recebe e-mail de confirmação, acompanha o chamado no portal, lê as respostas "
        "públicas e pode aprovar orçamentos de horas."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Título do pedido"),
            "description_html": _html_property("Descrição em HTML (sanitizada como no app)"),
            "priority": {"type": "string", "enum": list(PRIORITY_CHOICES), "description": "Prioridade"},
            "client": {
                "type": "string",
                "maxLength": 255,
                "description": "Cliente do pedido (UUID, nome ou CNPJ)",
            },
            "requester_email": {
                "type": "string",
                "maxLength": 254,
                "description": "E-mail do contato do cliente que pediu; torna o pedido visível a ele no portal",
            },
        },
        ["workspace_slug", "project", "name"],
    ),
    category="intake",
)
def create_intake_item(
    workspace_slug, project, name, description_html=None, priority="none", client=None, requester_email=None
):
    from plane.bgtasks.intake_portal_task import send_portal_ticket_created
    from plane.db.models import ClientContact
    from plane.db.models.state import StateGroup
    from plane.mcp.tools.clients import _get_client
    from plane.utils.conjo_billing import set_issue_client

    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if priority not in PRIORITY_CHOICES:
        raise MCPToolError(f"'priority' deve ser um destes: {', '.join(PRIORITY_CHOICES)}")
    project_instance = _get_project(workspace_slug, project)
    intake = Intake.objects.filter(project=project_instance).first()
    if intake is None:
        raise MCPToolError(f"A Entrada não está habilitada no projeto '{project_instance.identifier}'")

    client_instance = None
    if client:
        client_instance = _get_client(workspace_slug, client)
        if not client_instance.is_active:
            raise MCPToolError(f"O cliente '{client_instance.name}' está inativo")

    contact = portal = None
    email = str(requester_email or "").strip().lower()
    if email:
        if client_instance is None:
            raise MCPToolError("Informe o cliente (client) junto com requester_email")
        # Only registered contacts: the portal shows the ticket to whoever proves to own this address.
        contact = ClientContact.objects.filter(client=client_instance, email__iexact=email).first()
        if contact is None:
            raise MCPToolError(
                f"'{email}' não é contato do cliente '{client_instance.name}'; cadastre com add_client_contact"
            )
        portal = IntakePortal.objects.filter(project=project_instance, is_enabled=True).first()
        if portal is None:
            raise MCPToolError(f"O portal de chamados do projeto '{project_instance.identifier}' está desligado")

    actor = _mcp_actor()
    with transaction.atomic():
        triage_state = State.triage_objects.filter(project=project_instance).first()
        if triage_state is None:
            triage_state = State.objects.create(
                name="Triagem",
                group=StateGroup.TRIAGE.value,
                project=project_instance,
                color="#4E5355",
                sequence=65000,
                default=False,
            )
        issue = Issue(
            name=name,
            description_html=_clean_html(description_html),
            priority=priority,
            project=project_instance,
            state=triage_state,
        )
        issue.save(created_by_id=actor.id)
        intake_issue = IntakeIssue(
            intake=intake,
            project=project_instance,
            issue=issue,
            source=SourceType.PORTAL if contact else SourceType.IN_APP,
            source_email=contact.email if contact else None,
            extra={"requester_name": contact.name, "portal_anchor": portal.anchor} if contact else {},
        )
        intake_issue.save(created_by_id=actor.id)
        if client_instance is not None:
            set_issue_client(issue, client_instance)

    _record_activity("issue.activity.created", issue, actor, _issue_snapshot(issue), intake=intake_issue.id)
    if contact is not None:
        send_portal_ticket_created.delay(str(issue.id))

    return {
        **_serialize_issue(issue, include_description=True),
        "intake_status": "pending",
        "source": intake_issue.source,
        "requester_email": intake_issue.source_email,
    }


# ---------------------------------------------------------------------------
# Hour estimates (portal)
# ---------------------------------------------------------------------------


@register_tool(
    name="get_hours_estimate",
    description=(
        "Situação do orçamento de horas de um chamado do portal: horas, nota, PENDING/APPROVED/REJECTED, quem "
        "aprovou ou recusou e o motivo, e quem é o solicitante."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="intake",
)
def get_hours_estimate(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    ticket = _portal_ticket(issue)
    if ticket is None:
        return {"work_item": _issue_identifier(issue), "is_portal_ticket": False, "estimate": None}
    context = serialize_budget_context(issue.id)
    return {
        "work_item": _issue_identifier(issue),
        "is_portal_ticket": True,
        "requester": {"name": (ticket.extra or {}).get("requester_name") or "", "email": ticket.source_email},
        # the pending estimate (or the latest), every estimate sent and the approved total
        "estimate": context["budget"],
        "estimates": context["budgets"],
        "approved_hours": context["approved_hours"],
    }


@register_tool(
    name="send_hours_estimate",
    description=(
        "Envia ao cliente o orçamento de horas de um chamado do portal (VISÍVEL AO CLIENTE): ele recebe e-mail "
        "e aprova ou recusa no portal. Se há um orçamento pendente, ele é revisado; senão, cria um novo (depois de "
        "uma recusa, ou como orçamento adicional depois de uma aprovação — os aprovados se somam e nunca mudam). "
        "Quando aprovado, itens 'evolution' debitam essas horas do pacote do cliente. A nota aceita parágrafos, "
        "listas com '-' ou '1.' e **negrito**."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "hours": {"type": ["string", "number"], "maxLength": 10, "description": "Horas estimadas, ex.: 8 ou '6.5'"},
            "note": _text_property("Explicação para o cliente (aparece no portal e no e-mail)", MAX_BUDGET_NOTE_LENGTH),
        },
        ["workspace_slug", "work_item", "hours"],
    ),
    category="intake",
)
def send_hours_estimate(workspace_slug, work_item, hours, note=""):
    issue = _get_issue(workspace_slug, work_item)
    ticket = _portal_ticket(issue)
    if ticket is None:
        raise MCPToolError(
            f"{_issue_identifier(issue)} não veio do portal, então não há cliente para aprovar o orçamento"
        )
    note = _clean_text(note, "note", MAX_BUDGET_NOTE_LENGTH)
    budget, error = request_portal_budget(ticket, str(hours).replace(",", "."), note, created_by_id=_mcp_actor().id)
    if error:
        raise MCPToolError(error)
    return {
        "work_item": _issue_identifier(issue),
        "sent_to": ticket.source_email,
        "estimate": serialize_portal_budget(budget),
    }


# ---------------------------------------------------------------------------
# Attachments and estimate points
# ---------------------------------------------------------------------------


@register_tool(
    name="list_work_item_attachments",
    description=(
        "Lista os anexos de um item (nome, tipo, tamanho) com um link de download assinado que vale "
        f"{ATTACHMENT_URL_EXPIRATION // 60} minutos. Não compartilhe o link: quem o tiver baixa o arquivo."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_work_item_attachments(workspace_slug, work_item):
    from plane.settings.storage import S3Storage

    issue = _get_issue(workspace_slug, work_item)
    assets = FileAsset.objects.filter(
        issue=issue,
        workspace_id=issue.workspace_id,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        is_uploaded=True,
    ).order_by("created_at")[:100]
    storage = None
    attachments = []
    for asset in assets:
        attributes = asset.attributes or {}
        url = None
        try:
            storage = storage or S3Storage()
            # Always as a download: an inline link could render an uploaded HTML file.
            url = storage.generate_presigned_url(
                object_name=asset.asset.name,
                expiration=ATTACHMENT_URL_EXPIRATION,
                disposition="attachment",
                filename=attributes.get("name"),
            )
        except Exception:
            url = None
        attachments.append(
            {
                "id": str(asset.id),
                "name": attributes.get("name") or "arquivo",
                "type": attributes.get("type") or "",
                "size": int(asset.size or 0),
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "download_url": url or None,
            }
        )
    return {
        "work_item": _issue_identifier(issue),
        "attachments": attachments,
        "download_url_expires_in_seconds": ATTACHMENT_URL_EXPIRATION,
    }


@register_tool(
    name="list_estimate_points",
    description=(
        "Valores de estimativa (pontos) do projeto, para usar em estimate_point de create_work_item e "
        "update_work_item. Projetos sem estimativa devolvem lista vazia."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY}, ["workspace_slug", "project"]),
    category="work_items",
)
def list_estimate_points(workspace_slug, project):
    from plane.db.models import EstimatePoint

    project_instance = _get_project(workspace_slug, project)
    estimate = project_instance.estimate if project_instance.estimate_id else None
    if estimate is None or estimate.deleted_at is not None:
        return {"project": project_instance.identifier, "estimate": None, "points": []}
    points = EstimatePoint.objects.filter(estimate=estimate, project=project_instance).order_by("key")
    return {
        "project": project_instance.identifier,
        "estimate": {"id": str(estimate.id), "name": estimate.name, "type": estimate.type},
        "points": [
            {"id": str(point.id), "key": point.key, "value": point.value, "description": point.description}
            for point in points
        ],
    }


# ---------------------------------------------------------------------------
# Projects: archive
# ---------------------------------------------------------------------------


@register_tool(
    name="archive_project",
    description=(
        "Arquiva um projeto: ele e seus itens saem do board e das listas (os dados ficam). Pode ser desfeito com "
        "unarchive_project."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY}, ["workspace_slug", "project"]),
    category="projects",
)
def archive_project(workspace_slug, project):
    from plane.db.models import UserFavorite

    project_instance = _get_project(workspace_slug, project)
    if project_instance.archived_at is not None:
        raise MCPToolError(f"O projeto '{project_instance.identifier}' já está arquivado")
    project_instance.archived_at = timezone.now()
    project_instance.save()
    # Same as the app: favourites pointing at an archived project are dropped.
    UserFavorite.objects.filter(workspace_id=project_instance.workspace_id, project=project_instance.id).delete()
    return _serialize_project(project_instance)


@register_tool(
    name="unarchive_project",
    description="Traz de volta um projeto arquivado, com seus itens.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY}, ["workspace_slug", "project"]),
    category="projects",
)
def unarchive_project(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    if project_instance.archived_at is None:
        raise MCPToolError(f"O projeto '{project_instance.identifier}' não está arquivado")
    project_instance.archived_at = None
    project_instance.save()
    return _serialize_project(project_instance)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


@register_tool(
    name="server_info",
    description=(
        "O que este token pode fazer: ferramentas ativas por categoria, as que pedem confirm=true, limites de "
        "uso (requisições por minuto, lote, tamanhos) e em nome de quem as escritas ficam registradas."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    category="server",
)
def server_info():
    from plane.mcp import server as mcp_server
    from plane.mcp.models import MCPServer
    from plane.mcp.tools import TOOL_REGISTRY
    from plane.mcp.tools.handlers import BULK_CONFIRM_THRESHOLD, MAX_COMMENT_HTML_LENGTH, MAX_HTML_LENGTH
    from plane.mcp.views.server import MCPThrottle

    server = MCPServer.get_instance()
    enabled = [tool for tool in TOOL_REGISTRY.values() if server is None or server.is_tool_enabled(tool.name)]
    by_category = {}
    for tool in enabled:
        by_category[tool.category] = by_category.get(tool.category, 0) + 1
    confirm_tools = sorted(tool.name for tool in enabled if "confirm" in tool.input_schema.get("properties", {}))
    actor = _mcp_actor()
    return {
        "server": mcp_server.SERVER_INFO,
        "protocol_version": mcp_server.PROTOCOL_VERSION,
        "access": (
            "Token único da instância: lê e escreve em todos os workspaces, sem papel de usuário. Regras do app "
            "continuam valendo (convidados não viram responsáveis, páginas privadas de pessoas não aparecem, só "
            "comentários e registros feitos pelo MCP podem ser editados ou excluídos)."
        ),
        "writes_recorded_as": {"name": actor.display_name, "email": actor.email},
        "enabled_tools": len(enabled),
        "disabled_tools": sorted((server.disabled_tools or []) if server else []),
        "tools_by_category": dict(sorted(by_category.items())),
        "confirmation_required": confirm_tools,
        "limits": {
            "requests_per_minute_with_token": MCPThrottle.TOKEN_RATE,
            "requests_per_minute_without_token_per_ip": MCPThrottle.ANONYMOUS_RATE,
            "max_messages_per_batch": mcp_server.MAX_BATCH_SIZE,
            "max_items_per_bulk_call": 100,
            "bulk_confirm_above": BULK_CONFIRM_THRESHOLD,
            "max_html_length": MAX_HTML_LENGTH,
            "max_comment_html_length": MAX_COMMENT_HTML_LENGTH,
            "max_text_length": mcp_server.DEFAULT_MAX_STRING_LENGTH,
        },
        "now": timezone.now().isoformat(),
    }
