# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Domain handlers for the Plane MCP server.

Every handler is registered through `@register_tool` and receives plain
JSON-compatible arguments (already checked against its JSON schema by the
server). Handlers raise `MCPToolError` for expected failures (missing
entities, invalid payloads) — the MCP server turns them into `isError: True`
tool results. Descriptions and messages are in Brazilian Portuguese: the
company owner reads them in the admin panel.
"""

# Python imports
import datetime
import json
import re
import uuid
from urllib.parse import urlparse
from uuid import UUID

# Django imports
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError
from django.db.models import Prefetch, Q
from django.utils import timezone

# Module imports
from plane.db.models import (
    DEFAULT_STATES,
    Cycle,
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueType,
    Label,
    Module,
    Page,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.mcp.tools.registry import register_tool
from plane.utils.content_validator import validate_html_content

PRIORITY_CHOICES = ("urgent", "high", "medium", "low", "none")
MODULE_STATUS_CHOICES = ("backlog", "planned", "in-progress", "paused", "completed", "cancelled")
STATE_GROUP_CHOICES = ("backlog", "unstarted", "started", "completed", "cancelled")

# Limits shared by every tool module
MAX_NAME_LENGTH = 255
MAX_TEXT_LENGTH = 10_000
MAX_HTML_LENGTH = 500_000
MAX_COMMENT_HTML_LENGTH = 100_000
MAX_LIST_ITEMS = 100
# Above this many work items a bulk change must be confirmed.
BULK_CONFIRM_THRESHOLD = 20
# Project roles (same values as the app)
ROLE_ADMIN, ROLE_MEMBER, ROLE_GUEST = 20, 15, 5

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
_PROJECT_IDENTIFIER = re.compile(r"^[A-Z0-9]{1,12}$")


class MCPToolError(Exception):
    """Expected tool failure surfaced to the MCP client as an error result."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_uuid(value):
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _require_uuid(value, field):
    if not _is_uuid(value):
        raise MCPToolError(f"'{field}' deve ser um UUID")
    return str(value)


def _uuid_list(values, field, max_items=MAX_LIST_ITEMS):
    if values is None:
        return None
    if not isinstance(values, list):
        raise MCPToolError(f"'{field}' deve ser uma lista de UUIDs")
    if len(values) > max_items:
        raise MCPToolError(f"'{field}' aceita no máximo {max_items} itens")
    invalid = [str(value) for value in values if not _is_uuid(value)]
    if invalid:
        raise MCPToolError(f"'{field}' tem valores que não são UUID: {', '.join(invalid[:5])}")
    return list(dict.fromkeys(str(value) for value in values))


def _clean_text(value, field, max_length=MAX_TEXT_LENGTH, required=False):
    """Plain text: trimmed, required when asked, never longer than the column allows."""
    text = str(value or "").strip()
    if required and not text:
        raise MCPToolError(f"'{field}' é obrigatório")
    if len(text) > max_length:
        raise MCPToolError(f"'{field}' passa do limite de {max_length} caracteres")
    return text


def _clean_html(value, field="description_html", max_length=MAX_HTML_LENGTH):
    """HTML goes through the same sanitizer as the app (nh3): no scripts, handlers or javascript: links."""
    if value in (None, ""):
        return "<p></p>"
    if len(value) > max_length:
        raise MCPToolError(f"'{field}' passa do limite de {max_length} caracteres")
    is_valid, error, clean_html = validate_html_content(value)
    if not is_valid:
        raise MCPToolError(f"'{field}' tem HTML inválido: {error}")
    return clean_html or "<p></p>"


def _clean_color(value, field="color"):
    color = str(value or "").strip()
    if not _HEX_COLOR.match(color):
        raise MCPToolError(f"'{field}' deve ser uma cor hexadecimal, ex.: '#3B82F6'")
    return color


def _limit(value, default, maximum):
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        raise MCPToolError("'limit' deve ser um número inteiro")


def _require_confirm(confirm, action):
    if confirm is not True:
        raise MCPToolError(f"{action} Envie confirm=true para prosseguir.")


def _parse_date(value, field_name):
    if value in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise MCPToolError(f"'{field_name}' deve ser uma data ISO (AAAA-MM-DD)")


# ---------------------------------------------------------------------------
# Lookup helpers (always scoped by the workspace slug)
# ---------------------------------------------------------------------------


def _get_workspace(slug):
    workspace = Workspace.objects.filter(slug=str(slug or "")).first()
    if workspace is None:
        raise MCPToolError(f"O workspace '{slug}' não existe")
    return workspace


def _get_project(workspace_slug, project):
    """Resolve a project by UUID or by its identifier (e.g. `PLANE`)."""
    queryset = Project.objects.filter(workspace__slug=workspace_slug)
    if _is_uuid(project):
        instance = queryset.filter(pk=project).first()
    else:
        instance = queryset.filter(identifier=str(project or "").strip().upper()).first()
    if instance is None:
        raise MCPToolError(f"O projeto '{project}' não existe no workspace '{workspace_slug}'")
    return instance


def _get_issue(workspace_slug, issue):
    """Resolve an issue by UUID or by its human identifier (e.g. `PLANE-123`)."""
    queryset = Issue.objects.filter(workspace__slug=workspace_slug).select_related("project", "state")
    if _is_uuid(issue):
        instance = queryset.filter(pk=issue).first()
    else:
        try:
            project_identifier, sequence_id = str(issue).rsplit("-", 1)
            sequence_id = int(sequence_id)
        except (ValueError, AttributeError):
            raise MCPToolError(f"'{issue}' não é um UUID nem um identificador como 'MAN-123'")
        instance = queryset.filter(
            project__identifier=project_identifier.strip().upper(), sequence_id=sequence_id
        ).first()
    if instance is None:
        raise MCPToolError(f"O item '{issue}' não existe no workspace '{workspace_slug}'")
    return instance


def _workspace_user(workspace_slug, user_ref, field="member"):
    """An active workspace member by UUID or e-mail."""
    members = WorkspaceMember.objects.filter(workspace__slug=workspace_slug, is_active=True).select_related("member")
    if _is_uuid(user_ref):
        member = members.filter(member_id=user_ref).first()
    else:
        member = members.filter(member__email__iexact=str(user_ref or "").strip()).first()
    if member is None:
        raise MCPToolError(f"'{user_ref}' ({field}) não é membro ativo do workspace '{workspace_slug}'")
    return member.member


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_workspace(workspace):
    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "slug": workspace.slug,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


def _serialize_project(project):
    return {
        "id": str(project.id),
        "name": project.name,
        "identifier": project.identifier,
        "description": project.description,
        "workspace_id": str(project.workspace_id),
        "network": project.network,
        "emoji": project.emoji,
        "is_archived": project.archived_at is not None,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _serialize_user(user):
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "avatar": user.avatar_url,
    }


def _issue_identifier(issue):
    project_identifier = getattr(issue, "_project_identifier", None)
    if project_identifier is None:
        project_identifier = issue.project.identifier if issue.project_id else None
    return f"{project_identifier}-{issue.sequence_id}" if project_identifier else None


def issue_prefetch():
    """Current assignees and labels (the M2M fields would also return soft-deleted links)."""
    return (
        Prefetch("issue_assignee", queryset=IssueAssignee.objects.select_related("assignee")),
        Prefetch("label_issue", queryset=IssueLabel.objects.select_related("label")),
    )


def _active_assignees(issue):
    return [row.assignee for row in issue.issue_assignee.all() if row.assignee is not None]


def _active_labels(issue):
    return [row.label for row in issue.label_issue.all() if row.label is not None]


def _serialize_issue(issue, include_description=False):
    assignees = _active_assignees(issue)
    data = {
        "id": str(issue.id),
        "identifier": _issue_identifier(issue),
        "name": issue.name,
        "priority": issue.priority,
        "sequence_id": issue.sequence_id,
        "state_id": str(issue.state_id) if issue.state_id else None,
        "state": {"name": issue.state.name, "group": issue.state.group} if issue.state_id else None,
        "parent_id": str(issue.parent_id) if issue.parent_id else None,
        "project_id": str(issue.project_id),
        "workspace_id": str(issue.workspace_id),
        "start_date": issue.start_date.isoformat() if issue.start_date else None,
        "target_date": issue.target_date.isoformat() if issue.target_date else None,
        "assignee_ids": [str(user.id) for user in assignees],
        "assignee_emails": [user.email for user in assignees],
        "label_ids": [str(label.id) for label in _active_labels(issue)],
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }
    if include_description:
        data["description_html"] = issue.description_html
    return data


def _serialize_cycle(cycle):
    return {
        "id": str(cycle.id),
        "name": cycle.name,
        "description": cycle.description,
        "start_date": cycle.start_date.isoformat() if cycle.start_date else None,
        "end_date": cycle.end_date.isoformat() if cycle.end_date else None,
        "project_id": str(cycle.project_id),
        "workspace_id": str(cycle.workspace_id),
        "is_archived": cycle.archived_at is not None,
        "created_at": cycle.created_at.isoformat() if cycle.created_at else None,
        "updated_at": cycle.updated_at.isoformat() if cycle.updated_at else None,
    }


def _serialize_module(module):
    return {
        "id": str(module.id),
        "name": module.name,
        "description": module.description,
        "status": module.status,
        "start_date": module.start_date.isoformat() if module.start_date else None,
        "target_date": module.target_date.isoformat() if module.target_date else None,
        "project_id": str(module.project_id),
        "workspace_id": str(module.workspace_id),
        "is_archived": module.archived_at is not None,
        "created_at": module.created_at.isoformat() if module.created_at else None,
        "updated_at": module.updated_at.isoformat() if module.updated_at else None,
    }


def _serialize_state(state):
    return {
        "id": str(state.id),
        "name": state.name,
        "color": state.color,
        "group": state.group,
        "sequence": state.sequence,
        "default": state.default,
        "project_id": str(state.project_id),
    }


def _serialize_label(label):
    return {
        "id": str(label.id),
        "name": label.name,
        "color": label.color,
        "description": label.description,
        "project_id": str(label.project_id) if label.project_id else None,
        "workspace_id": str(label.workspace_id),
    }


def _serialize_page(page):
    return {
        "id": str(page.id),
        "name": page.name,
        "access": "private" if page.access == 1 else "public",
        "is_locked": page.is_locked,
        "is_archived": page.archived_at is not None,
        "owned_by_id": str(page.owned_by_id),
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


# ---------------------------------------------------------------------------
# JSON schema fragments
# ---------------------------------------------------------------------------

_WORKSPACE_SLUG_PROPERTY = {
    "workspace_slug": {
        "type": "string",
        "maxLength": 100,
        "description": "Slug do workspace, ex.: 'conjo'",
    }
}

_PROJECT_PROPERTY = {
    "project": {
        "type": "string",
        "maxLength": 100,
        "description": "UUID ou identificador do projeto, ex.: 'MAN'",
    }
}

_WORK_ITEM_PROPERTY = {
    "work_item": {
        "type": "string",
        "maxLength": 100,
        "description": "UUID ou identificador do item, ex.: 'MAN-123'",
    }
}

_CONFIRM_PROPERTY = {
    "confirm": {
        "type": "boolean",
        "description": "Obrigatório e igual a true: confirma uma ação irreversível",
    }
}


def _name_property(description):
    return {"type": "string", "maxLength": MAX_NAME_LENGTH, "description": description}


def _text_property(description, max_length=MAX_TEXT_LENGTH):
    return {"type": "string", "maxLength": max_length, "description": description}


def _html_property(description, max_length=MAX_HTML_LENGTH):
    return {"type": "string", "maxLength": max_length, "description": description}


def _uuid_list_property(description, max_items=MAX_LIST_ITEMS):
    return {
        "type": "array",
        "items": {"type": "string", "maxLength": 100},
        "maxItems": max_items,
        "description": description,
    }


def _date_property(description="Data ISO (AAAA-MM-DD)"):
    return {"type": "string", "maxLength": 40, "description": description}


def _limit_property(default, maximum, description="Quantidade máxima de resultados"):
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": maximum,
        "default": default,
        "description": f"{description} (padrão {default}, máximo {maximum})",
    }


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_workspaces",
    description="Lista todos os workspaces desta instância do Tasks.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    category="workspaces",
)
def list_workspaces():
    workspaces = Workspace.objects.all().order_by("name")
    return {"workspaces": [_serialize_workspace(workspace) for workspace in workspaces]}


@register_tool(
    name="retrieve_workspace",
    description="Detalhes de um workspace pelo slug.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY},
        "required": ["workspace_slug"],
        "additionalProperties": False,
    },
    category="workspaces",
)
def retrieve_workspace(workspace_slug):
    return _serialize_workspace(_get_workspace(workspace_slug))


# ---------------------------------------------------------------------------
# Project tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_projects",
    description="Lista os projetos de um workspace (inclusive arquivados, marcados em is_archived).",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY},
        "required": ["workspace_slug"],
        "additionalProperties": False,
    },
    category="projects",
)
def list_projects(workspace_slug):
    _get_workspace(workspace_slug)
    projects = Project.objects.filter(workspace__slug=workspace_slug).order_by("name")
    return {"projects": [_serialize_project(project) for project in projects]}


@register_tool(
    name="retrieve_project",
    description="Detalhes de um projeto pelo UUID ou identificador.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="projects",
)
def retrieve_project(workspace_slug, project):
    return _serialize_project(_get_project(workspace_slug, project))


@register_tool(
    name="create_project",
    description=(
        "Cria um projeto no workspace com os estados padrão (Backlog, A fazer, Em andamento, Concluída, Cancelada). "
        "Informe admin (e-mail de um membro do workspace) para que alguém administre o projeto; sem isso o "
        "projeto nasce sem membros e só aparece para quem for adicionado depois (add_project_member)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            "name": _name_property("Nome do projeto"),
            "identifier": {
                "type": "string",
                "description": "Identificador curto em maiúsculas usado nos itens, ex.: 'MAN' (até 12 letras/números)",
                "maxLength": 12,
            },
            "description": _text_property("Descrição em texto simples (opcional)"),
            "admin": {
                "type": "string",
                "maxLength": 254,
                "description": "E-mail ou UUID do membro do workspace que vira administrador do projeto",
            },
        },
        "required": ["workspace_slug", "name", "identifier"],
        "additionalProperties": False,
    },
    category="projects",
)
def create_project(workspace_slug, name, identifier, description="", admin=None):
    from plane.db.models import ProjectUserProperty

    workspace = _get_workspace(workspace_slug)
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    identifier = str(identifier or "").strip().upper()
    if not _PROJECT_IDENTIFIER.match(identifier):
        raise MCPToolError("'identifier' deve ter de 1 a 12 letras ou números, sem espaços")
    description = _clean_text(description, "description")
    admin_user = _workspace_user(workspace_slug, admin, "admin") if admin else None

    if Project.objects.filter(workspace=workspace, identifier=identifier).exists():
        raise MCPToolError(f"Já existe um projeto com o identificador '{identifier}' neste workspace")
    if Project.objects.filter(workspace=workspace, name__iexact=name).exists():
        raise MCPToolError(f"Já existe um projeto chamado '{name}' neste workspace")

    try:
        project = Project.objects.create(
            name=name,
            identifier=identifier,
            description=description,
            workspace=workspace,
        )
        State.objects.bulk_create(
            [
                State(
                    name=state["name"],
                    color=state["color"],
                    project=project,
                    workspace=workspace,
                    sequence=state["sequence"],
                    group=state["group"],
                    default=state.get("default", False),
                )
                for state in DEFAULT_STATES
            ]
        )
        # Point the default state at the seeded "default" state
        default_state = State.objects.filter(project=project, default=True).first()
        if default_state:
            project.default_state = default_state
            project.save(update_fields=["default_state", "updated_at"])
    except IntegrityError:
        raise MCPToolError(f"Já existe um projeto com o nome '{name}' ou o identificador '{identifier}'")

    if admin_user is not None:
        workspace_role = (
            WorkspaceMember.objects.filter(workspace=workspace, member=admin_user, is_active=True)
            .values_list("role", flat=True)
            .first()
        )
        # Same rule as the app: nobody gets a project role above their workspace role.
        ProjectMember.objects.create(project=project, member=admin_user, role=min(ROLE_ADMIN, workspace_role or 5))
        ProjectUserProperty.objects.get_or_create(project=project, user=admin_user, workspace=workspace)

    return _serialize_project(project)


# ---------------------------------------------------------------------------
# Member tools
# ---------------------------------------------------------------------------

_ROLE_NAMES = {ROLE_ADMIN: "admin", ROLE_MEMBER: "member", ROLE_GUEST: "guest"}


@register_tool(
    name="list_workspace_members",
    description="Lista os membros ativos do workspace com o papel (admin, member, guest).",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY},
        "required": ["workspace_slug"],
        "additionalProperties": False,
    },
    category="members",
)
def list_workspace_members(workspace_slug):
    _get_workspace(workspace_slug)
    members = WorkspaceMember.objects.filter(workspace__slug=workspace_slug, is_active=True).select_related("member")
    return {
        "members": [
            {**_serialize_user(member.member), "role": _ROLE_NAMES.get(member.role, member.role)}
            for member in members
            if member.member is not None
        ]
    }


@register_tool(
    name="list_project_members",
    description=(
        "Lista os membros ativos de um projeto com o papel. Convidados (guest) não podem ser responsáveis por "
        "itens nem lançar horas."
    ),
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="members",
)
def list_project_members(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    members = ProjectMember.objects.filter(project=project_instance, is_active=True).select_related("member")
    return {
        "members": [
            {**_serialize_user(member.member), "role": _ROLE_NAMES.get(member.role, member.role)}
            for member in members
            if member.member is not None
        ]
    }


# ---------------------------------------------------------------------------
# Work item tools
# ---------------------------------------------------------------------------


def _filtered_issues(
    workspace_slug,
    project=None,
    query=None,
    state_id=None,
    priority=None,
    assignee_id=None,
    label_id=None,
    cycle_id=None,
    module_id=None,
    state_group=None,
    parent=None,
    archived=False,
    client=None,
    due_before=None,
    overdue=False,
):
    # The board: no requests still in triage, no drafts; archived items only when asked for.
    if archived:
        base = Issue.objects.filter(archived_at__isnull=False, is_draft=False)
    else:
        base = Issue.issue_objects.all()
    queryset = (
        base.filter(workspace__slug=workspace_slug)
        .select_related("project", "state")
        .prefetch_related(*issue_prefetch())
    )
    if project is not None:
        queryset = queryset.filter(project=_get_project(workspace_slug, project))
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(description_stripped__icontains=query))
    if state_id:
        queryset = queryset.filter(state_id=state_id)
    if priority:
        queryset = queryset.filter(priority=priority)
    if assignee_id:
        queryset = queryset.filter(issue_assignee__assignee_id=assignee_id, issue_assignee__deleted_at__isnull=True)
    if label_id:
        queryset = queryset.filter(label_issue__label_id=label_id, label_issue__deleted_at__isnull=True)
    if cycle_id:
        queryset = queryset.filter(issue_cycle__cycle_id=cycle_id, issue_cycle__deleted_at__isnull=True)
    if module_id:
        queryset = queryset.filter(issue_module__module_id=module_id, issue_module__deleted_at__isnull=True)
    if state_group:
        queryset = queryset.filter(state__group=state_group)
    if parent:
        queryset = queryset.filter(parent=_get_issue(workspace_slug, parent))
    if due_before:
        queryset = queryset.filter(target_date__lte=due_before)
    if overdue:
        queryset = queryset.filter(target_date__lt=timezone.localdate()).exclude(
            state__group__in=("completed", "cancelled")
        )
    if client:
        from plane.mcp.tools.clients import _get_client
        from plane.utils.conjo_billing import client_issues

        queryset = queryset.filter(id__in=client_issues(_get_client(workspace_slug, client)).values("id"))
    return queryset.order_by("-created_at").distinct()


@register_tool(
    name="list_work_items",
    description=(
        "Lista itens do board de um workspace ou projeto (sem pedidos ainda na Entrada). Filtros combináveis: "
        "estado, grupo de estado, prioridade, responsável (UUID ou e-mail), etiqueta, ciclo, módulo, item pai, "
        "cliente, prazo até uma data (due_before) e atrasados (overdue: prazo vencido e não concluídos). "
        "Pagina com limit/offset."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "state_id": {"type": "string", "maxLength": 100, "description": "UUID do estado"},
            "priority": {
                "type": "string",
                "enum": list(PRIORITY_CHOICES),
                "description": "Prioridade",
            },
            "assignee": {
                "type": "string",
                "maxLength": 254,
                "description": "Responsável: e-mail ou UUID do membro (ex.: 'meus itens')",
            },
            "assignee_id": {"type": "string", "maxLength": 100, "description": "UUID do responsável (legado)"},
            "label_id": {"type": "string", "maxLength": 100, "description": "UUID da etiqueta"},
            "cycle_id": {"type": "string", "maxLength": 100, "description": "UUID do ciclo"},
            "module_id": {"type": "string", "maxLength": 100, "description": "UUID do módulo"},
            "state_group": {
                "type": "string",
                "enum": list(STATE_GROUP_CHOICES),
                "description": "Grupo de estado (ex.: 'started' para tudo em andamento)",
            },
            "parent": {"type": "string", "maxLength": 100, "description": "Só os subitens deste item"},
            "client": {
                "type": "string",
                "maxLength": 255,
                "description": "Só itens deste cliente (UUID, nome ou CNPJ), pela etiqueta em boards compartilhados",
            },
            "due_before": _date_property("Só itens com prazo até esta data (AAAA-MM-DD), inclusive"),
            "overdue": {"type": "boolean", "description": "Só itens atrasados (prazo vencido e não concluídos)"},
            "archived": {"type": "boolean", "description": "Lista os itens arquivados", "default": False},
            "limit": _limit_property(50, 200),
            "offset": {"type": "integer", "minimum": 0, "description": "Pula esta quantidade (paginação)"},
        },
        "required": ["workspace_slug"],
        "additionalProperties": False,
    },
    category="work_items",
)
def list_work_items(
    workspace_slug,
    project=None,
    state_id=None,
    priority=None,
    assignee=None,
    assignee_id=None,
    label_id=None,
    cycle_id=None,
    module_id=None,
    state_group=None,
    parent=None,
    client=None,
    due_before=None,
    overdue=False,
    archived=False,
    limit=50,
    offset=0,
):
    _get_workspace(workspace_slug)
    if priority is not None and priority not in PRIORITY_CHOICES:
        raise MCPToolError(f"'priority' deve ser um destes: {', '.join(PRIORITY_CHOICES)}")
    if state_group is not None and state_group not in STATE_GROUP_CHOICES:
        raise MCPToolError(f"'state_group' deve ser um destes: {', '.join(STATE_GROUP_CHOICES)}")
    for name, value in (
        ("state_id", state_id),
        ("assignee_id", assignee_id),
        ("label_id", label_id),
        ("cycle_id", cycle_id),
        ("module_id", module_id),
    ):
        if value:
            _require_uuid(value, name)
    if assignee:
        assignee_id = str(_workspace_user(workspace_slug, assignee, "assignee").id)
    limit = _limit(limit, 50, 200)
    offset = max(0, int(offset or 0))
    queryset = _filtered_issues(
        workspace_slug,
        project=project,
        state_id=state_id,
        priority=priority,
        assignee_id=assignee_id,
        label_id=label_id,
        cycle_id=cycle_id,
        module_id=module_id,
        state_group=state_group,
        parent=parent,
        archived=bool(archived),
        client=client,
        due_before=_parse_date(due_before, "due_before"),
        overdue=bool(overdue),
    )
    total = queryset.count()
    issues = queryset[offset : offset + limit]
    return {
        "work_items": [_serialize_issue(issue) for issue in issues],
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
    }


@register_tool(
    name="retrieve_work_item",
    description=(
        "Um item completo pelo UUID ou identificador ('MAN-123'): descrição, responsáveis, etiquetas, pai e "
        "subitens, ciclo, módulos, relações, estimativa (pontos), cliente e situação na Entrada."
    ),
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY},
        "required": ["workspace_slug", "work_item"],
        "additionalProperties": False,
    },
    category="work_items",
)
def retrieve_work_item(workspace_slug, work_item):
    from plane.db.models import CycleIssue, FileAsset, IntakeIssue, IssueLink, ModuleIssue
    from plane.mcp.tools.board import _relations_of
    from plane.utils.conjo_billing import client_resolution

    issue = _get_issue(workspace_slug, work_item)
    data = _serialize_issue(issue, include_description=True)

    cycle = CycleIssue.objects.filter(issue=issue).select_related("cycle").first()
    intake = IntakeIssue.objects.filter(issue=issue).first()
    client, client_via = client_resolution(issue)
    estimate_point = issue.estimate_point if issue.estimate_point_id else None
    data.update(
        assignees=[
            {"id": str(user.id), "display_name": user.display_name, "email": user.email}
            for user in _active_assignees(issue)
        ],
        labels=[{"id": str(label.id), "name": label.name} for label in _active_labels(issue)],
        parent=_issue_identifier(issue.parent) if issue.parent_id else None,
        sub_work_items=[
            _issue_identifier(child) for child in Issue.issue_objects.filter(parent=issue).order_by("sequence_id")
        ],
        cycle={"id": str(cycle.cycle_id), "name": cycle.cycle.name} if cycle else None,
        modules=[
            {"id": str(link.module_id), "name": link.module.name}
            for link in ModuleIssue.objects.filter(issue=issue).select_related("module")
        ],
        relations=_relations_of(issue),
        links=IssueLink.objects.filter(issue=issue).count(),
        attachments=FileAsset.objects.filter(
            issue=issue, entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT, is_uploaded=True
        ).count(),
        estimate_point={"id": str(estimate_point.id), "value": estimate_point.value} if estimate_point else None,
        is_archived=issue.archived_at is not None,
        intake_status={-2: "pending", -1: "declined", 0: "snoozed", 1: "accepted", 2: "duplicate"}.get(intake.status)
        if intake
        else None,
        visible_to_client=_client_audience(issue),
        completed_at=issue.completed_at.isoformat() if issue.completed_at else None,
        client={"id": str(client.id), "name": client.name, "via": client_via} if client else None,
    )
    return data


@register_tool(
    name="search_work_items",
    description="Busca texto no título e na descrição dos itens do board de um workspace ou projeto.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "query": {"type": "string", "maxLength": 255, "description": "Texto a buscar"},
            "limit": _limit_property(25, 100),
        },
        "required": ["workspace_slug", "query"],
        "additionalProperties": False,
    },
    category="work_items",
)
def search_work_items(workspace_slug, query, project=None, limit=25):
    _get_workspace(workspace_slug)
    query = _clean_text(query, "query", MAX_NAME_LENGTH, required=True)
    limit = _limit(limit, 25, 100)
    issues = _filtered_issues(workspace_slug, project=project, query=query)[:limit]
    return {"work_items": [_serialize_issue(issue) for issue in issues]}


def _validate_priority(priority):
    if priority is not None and priority not in PRIORITY_CHOICES:
        raise MCPToolError(f"'priority' deve ser um destes: {', '.join(PRIORITY_CHOICES)}")


def _validate_state(project_instance, state_id):
    if state_id in (None, ""):
        return None
    state = State.objects.filter(project=project_instance, pk=state_id).first() if _is_uuid(state_id) else None
    if state is None:
        raise MCPToolError(f"O estado '{state_id}' não existe no projeto '{project_instance.identifier}'")
    return state


def _validate_parent(workspace_slug, project_instance, parent, child=None):
    """Parent in the same project, never the item itself nor one of its descendants."""
    if parent in (None, ""):
        return None
    parent_issue = _get_issue(workspace_slug, parent)
    if parent_issue.project_id != project_instance.id:
        raise MCPToolError("O item pai precisa ser do mesmo projeto")
    if child is not None:
        ancestor = parent_issue
        for _ in range(50):
            if ancestor is None:
                break
            if ancestor.id == child.id:
                raise MCPToolError("Um item não pode ser pai de si mesmo nem do próprio pai (parent)")
            ancestor = ancestor.parent
    return parent_issue


def _validate_assignees(project_instance, assignee_ids):
    """Assignees must be active members of the project, never guests (the app's rule)."""
    assignee_ids = _uuid_list(assignee_ids, "assignee_ids")
    if not assignee_ids:
        return assignee_ids
    valid = {
        str(member_id)
        for member_id in ProjectMember.objects.filter(
            project=project_instance, is_active=True, role__gte=ROLE_MEMBER, member_id__in=assignee_ids
        ).values_list("member_id", flat=True)
    }
    invalid = [member_id for member_id in assignee_ids if member_id not in valid]
    if invalid:
        raise MCPToolError(
            "Responsáveis precisam ser membros ativos do projeto (convidados não podem): " + ", ".join(invalid)
        )
    return assignee_ids


def _validate_labels(project_instance, label_ids):
    label_ids = _uuid_list(label_ids, "label_ids")
    if not label_ids:
        return label_ids
    valid = {
        str(label_id)
        for label_id in Label.objects.filter(project=project_instance, id__in=label_ids).values_list("id", flat=True)
    }
    invalid = [label_id for label_id in label_ids if label_id not in valid]
    if invalid:
        raise MCPToolError(f"Etiquetas que não são do projeto '{project_instance.identifier}': {', '.join(invalid)}")
    return label_ids


def _resolve_estimate_point(project_instance, estimate_point):
    """A point of the project's active estimate, by UUID or by value (e.g. '3' or 'M'); '' clears."""
    from plane.db.models import EstimatePoint

    if estimate_point == "":
        return None
    if not project_instance.estimate_id:
        raise MCPToolError(f"O projeto '{project_instance.identifier}' não usa estimativas")
    points = EstimatePoint.objects.filter(estimate_id=project_instance.estimate_id, project=project_instance)
    if _is_uuid(estimate_point):
        point = points.filter(pk=estimate_point).first()
    else:
        point = points.filter(value__iexact=str(estimate_point).strip()).first()
    if point is None:
        values = ", ".join(points.order_by("key").values_list("value", flat=True))
        raise MCPToolError(f"Estimativa '{estimate_point}' não existe no projeto. Valores possíveis: {values}")
    return point


def _set_issue_assignees(issue, project_instance, assignee_ids):
    """Replace the assignees; ``assignee_ids`` must come from _validate_assignees."""
    if assignee_ids is None:
        return
    IssueAssignee.objects.filter(issue=issue).delete()
    IssueAssignee.objects.bulk_create(
        [
            IssueAssignee(
                issue=issue,
                assignee_id=member_id,
                project=project_instance,
                workspace=issue.workspace,
            )
            for member_id in assignee_ids
        ],
        batch_size=10,
        ignore_conflicts=True,
    )


def _set_issue_labels(issue, project_instance, label_ids):
    """Replace the labels; ``label_ids`` must come from _validate_labels."""
    if label_ids is None:
        return
    IssueLabel.objects.filter(issue=issue).delete()
    IssueLabel.objects.bulk_create(
        [
            IssueLabel(
                issue=issue,
                label_id=label_id,
                project=project_instance,
                workspace=issue.workspace,
            )
            for label_id in label_ids
        ],
        batch_size=10,
        ignore_conflicts=True,
    )


def _client_audience(issue):
    """Who outside the team can read the item's public comments, or None when nobody can.

    Same rules as the app: the requester of a ticket that came from the request portal, or anyone who
    opens the project's published board when it accepts comments.
    """
    from plane.db.models import DeployBoard, IntakeIssue
    from plane.db.models.intake import SourceType

    intake = (
        IntakeIssue.objects.filter(issue=issue, source=SourceType.PORTAL, source_email__isnull=False)
        .exclude(source_email="")
        .first()
    )
    if intake is not None:
        name = (intake.extra or {}).get("requester_name") or ""
        return f"portal: {name} <{intake.source_email}>" if name else f"portal: {intake.source_email}"
    if DeployBoard.objects.filter(
        entity_name="project", entity_identifier=issue.project_id, is_disabled=False, is_comments_enabled=True
    ).exists():
        return "board publicado do projeto"
    return None


# ---------------------------------------------------------------------------
# Activity (Conjo): MCP writes are recorded like the app's, so they show in the
# work item history and reach notifications and the project's chat room.
# ---------------------------------------------------------------------------

MCP_BOT_USERNAME = "conjo_mcp_bot"


def _mcp_actor():
    """The "Assistente (MCP)" bot: the MCP token belongs to the instance, not to a person."""
    bot = User.objects.filter(username=MCP_BOT_USERNAME).first()
    if bot is not None:
        return bot
    host = urlparse(getattr(settings, "TASKS_PUBLIC_URL", "") or settings.WEB_URL or "").hostname or "tasks.local"
    try:
        return User.objects.create(
            username=MCP_BOT_USERNAME,
            display_name="Assistente (MCP)",
            first_name="Assistente",
            last_name="(MCP)",
            is_bot=True,
            bot_type="CONJO_MCP",
            email=f"mcp-bot@{host}",
            password=make_password(uuid.uuid4().hex),
            is_password_autoset=True,
        )
    except IntegrityError:
        return User.objects.filter(username=MCP_BOT_USERNAME).first()


def _record_activity(activity_type, issue, actor, requested_data, current_instance=None, intake=None):
    from plane.bgtasks.issue_activities_task import issue_activity

    kwargs = {}
    if intake is not None:
        kwargs["intake"] = str(intake)
    issue_activity.delay(
        type=activity_type,
        requested_data=json.dumps(requested_data, cls=DjangoJSONEncoder),
        current_instance=json.dumps(current_instance, cls=DjangoJSONEncoder) if current_instance is not None else None,
        issue_id=str(issue.id),
        actor_id=str(actor.id),
        project_id=str(issue.project_id),
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=getattr(settings, "TASKS_PUBLIC_URL", None) or settings.WEB_URL,
        **kwargs,
    )


def _issue_snapshot(issue):
    """Tracked fields in the shape the activity pipeline compares (ids as strings)."""
    return {
        "name": issue.name,
        "description_html": issue.description_html,
        "priority": issue.priority,
        "state_id": str(issue.state_id) if issue.state_id else None,
        "start_date": issue.start_date.isoformat() if issue.start_date else None,
        "target_date": issue.target_date.isoformat() if issue.target_date else None,
        "parent_id": str(issue.parent_id) if issue.parent_id else None,
        "estimate_point": str(issue.estimate_point_id) if issue.estimate_point_id else None,
        "assignee_ids": [
            str(a) for a in IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True)
        ],
        "label_ids": [
            str(label) for label in IssueLabel.objects.filter(issue=issue).values_list("label_id", flat=True)
        ],
    }


_WORK_ITEM_FIELDS = {
    "name": _name_property("Título do item"),
    "description_html": _html_property("Descrição em HTML (sanitizada como no app)"),
    "priority": {"type": "string", "enum": list(PRIORITY_CHOICES), "description": "Prioridade"},
    "state_id": {"type": "string", "maxLength": 100, "description": "UUID do estado (list_states)"},
    "start_date": _date_property("Data de início ISO (AAAA-MM-DD); '' limpa"),
    "target_date": _date_property("Prazo ISO (AAAA-MM-DD); '' limpa"),
    "assignee_ids": _uuid_list_property("UUIDs dos responsáveis (membros do projeto, não convidados); substitui"),
    "label_ids": _uuid_list_property("UUIDs das etiquetas do projeto; substitui as atuais"),
    "estimate_point": {
        "type": "string",
        "maxLength": 255,
        "description": "Estimativa do item: valor (ex.: '3', 'M') ou UUID do ponto (list_estimate_points); '' limpa",
    },
}


@register_tool(
    name="create_work_item",
    description=(
        "Cria um item no board de um projeto (registra no histórico e notifica). Opcionalmente define estado, "
        "prioridade, datas, responsáveis, etiquetas, item pai, estimativa e cliente. Para um pedido que deve "
        "passar pela triagem, use create_intake_item."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_WORK_ITEM_FIELDS,
            "parent": {
                "type": "string",
                "maxLength": 100,
                "description": "Cria como subitem deste item (identificador ou UUID, mesmo projeto)",
            },
            "client": {
                "type": "string",
                "maxLength": 255,
                "description": "Cliente do item (UUID, nome ou CNPJ); a etiqueta do cliente é aplicada",
            },
        },
        "required": ["workspace_slug", "project", "name"],
        "additionalProperties": False,
    },
    category="work_items",
)
def create_work_item(
    workspace_slug,
    project,
    name,
    description_html=None,
    priority=None,
    state_id=None,
    start_date=None,
    target_date=None,
    assignee_ids=None,
    label_ids=None,
    parent=None,
    client=None,
    estimate_point=None,
):
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    _validate_priority(priority)
    project_instance = _get_project(workspace_slug, project)
    state = _validate_state(project_instance, state_id)
    parent_issue = _validate_parent(workspace_slug, project_instance, parent)
    assignee_ids = _validate_assignees(project_instance, assignee_ids)
    label_ids = _validate_labels(project_instance, label_ids)
    point = _resolve_estimate_point(project_instance, estimate_point) if estimate_point else None
    start = _parse_date(start_date, "start_date")
    target = _parse_date(target_date, "target_date")
    if start and target and start > target:
        raise MCPToolError("'start_date' não pode ser depois de 'target_date'")
    client_instance = None
    if client:
        from plane.mcp.tools.clients import _get_client

        client_instance = _get_client(workspace_slug, client)
        if not client_instance.is_active:
            raise MCPToolError(f"O cliente '{client_instance.name}' está inativo")

    issue_type = IssueType.objects.filter(project_issue_types__project_id=project_instance.id, is_default=True).first()

    actor = _mcp_actor()
    issue = Issue(
        name=name,
        description_html=_clean_html(description_html),
        priority=priority or "none",
        state=state or project_instance.default_state,
        project=project_instance,
        type=issue_type,
        start_date=start,
        target_date=target,
        parent=parent_issue,
        estimate_point=point,
    )
    # No request user behind the MCP token: name the bot as the author explicitly.
    issue.save(created_by_id=actor.id)

    _set_issue_assignees(issue, project_instance, assignee_ids)
    _set_issue_labels(issue, project_instance, label_ids)
    if client_instance is not None:
        from plane.utils.conjo_billing import set_issue_client

        set_issue_client(issue, client_instance)
    _record_activity("issue.activity.created", issue, actor, _issue_snapshot(issue))

    return _serialize_issue(issue, include_description=True)


@register_tool(
    name="update_work_item",
    description=(
        "Altera campos de um item; só os campos enviados mudam (registra no histórico e notifica os "
        "envolvidos). Responsáveis e etiquetas, quando enviados, substituem os atuais. Mudanças de estado, "
        "prioridade, prazo, responsáveis e etiquetas em chamados do portal geram e-mail ao cliente."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            **_WORK_ITEM_FIELDS,
            "parent": {
                "type": "string",
                "maxLength": 100,
                "description": "Item pai (identificador ou UUID, mesmo projeto); '' desvincula",
            },
        },
        "required": ["workspace_slug", "work_item"],
        "additionalProperties": False,
    },
    category="work_items",
)
def update_work_item(
    workspace_slug,
    work_item,
    name=None,
    description_html=None,
    priority=None,
    state_id=None,
    start_date=None,
    target_date=None,
    assignee_ids=None,
    label_ids=None,
    parent=None,
    estimate_point=None,
):
    issue = _get_issue(workspace_slug, work_item)
    project_instance = issue.project
    _validate_priority(priority)
    # Validate everything before touching the item, so a bad value never leaves a half-applied change.
    assignee_ids = _validate_assignees(project_instance, assignee_ids)
    label_ids = _validate_labels(project_instance, label_ids)
    if name is not None:
        name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if description_html is not None:
        description_html = _clean_html(description_html)
    state = _validate_state(project_instance, state_id) if state_id is not None else None
    if state_id == "":
        raise MCPToolError("'state_id' não pode ser vazio")
    parent_issue = (
        _validate_parent(workspace_slug, project_instance, parent, child=issue) if parent is not None else None
    )
    point = _resolve_estimate_point(project_instance, estimate_point) if estimate_point is not None else None
    start = _parse_date(start_date, "start_date") if start_date is not None else issue.start_date
    target = _parse_date(target_date, "target_date") if target_date is not None else issue.target_date
    if start and target and start > target:
        raise MCPToolError("'start_date' não pode ser depois de 'target_date'")

    before = _issue_snapshot(issue)

    update_fields = []
    if name is not None:
        issue.name = name
        update_fields.append("name")
    if description_html is not None:
        issue.description_html = description_html
        update_fields.append("description_html")
    if priority is not None:
        issue.priority = priority
        update_fields.append("priority")
    if state is not None:
        issue.state = state
        update_fields.append("state")
    if start_date is not None:
        issue.start_date = start
        update_fields.append("start_date")
    if target_date is not None:
        issue.target_date = target
        update_fields.append("target_date")
    if parent is not None:
        issue.parent = parent_issue
        update_fields.append("parent")
    if estimate_point is not None:
        issue.estimate_point = point
        update_fields.append("estimate_point")

    if update_fields:
        update_fields.append("updated_at")
        issue.save(update_fields=update_fields)

    _set_issue_assignees(issue, project_instance, assignee_ids)
    _set_issue_labels(issue, project_instance, label_ids)

    after = _issue_snapshot(issue)
    changed = {field: value for field, value in after.items() if value != before[field]}
    if changed:
        _record_activity(
            "issue.activity.updated",
            issue,
            _mcp_actor(),
            changed,
            {field: before[field] for field in changed},
        )

    return _serialize_issue(issue, include_description=True)


@register_tool(
    name="add_work_item_comment",
    description=(
        "Comenta num item (registra no histórico e notifica a equipe). Por padrão é NOTA INTERNA, só a equipe "
        "vê. public=true publica uma RESPOSTA AO CLIENTE: fica visível no portal para quem abriu o chamado "
        "(e ele recebe e-mail) ou no board publicado; só é aceito em itens que vieram do portal ou de projetos "
        "com board publicado com comentários."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "comment_html": _html_property("Corpo do comentário em HTML", MAX_COMMENT_HTML_LENGTH),
            "public": {
                "type": "boolean",
                "default": False,
                "description": "true = visível ao cliente (resposta pública); false/omitido = nota interna",
            },
        },
        "required": ["workspace_slug", "work_item", "comment_html"],
        "additionalProperties": False,
    },
    category="work_items",
)
def add_work_item_comment(workspace_slug, work_item, comment_html, public=False):
    from plane.app.serializers import IssueCommentSerializer

    issue = _get_issue(workspace_slug, work_item)
    clean = _clean_html(comment_html, "comment_html", MAX_COMMENT_HTML_LENGTH)
    if clean.replace("<p></p>", "").strip() == "":
        raise MCPToolError("'comment_html' é obrigatório")
    audience = _client_audience(issue) if public else None
    if public and audience is None:
        raise MCPToolError(
            f"{_issue_identifier(issue)} não tem cliente que leia comentários públicos (não veio do portal e o "
            "board do projeto não está publicado com comentários). Envie como nota interna."
        )
    actor = _mcp_actor()
    comment = IssueComment(
        issue=issue,
        project=issue.project,
        comment_html=clean,
        actor=actor,
        access="EXTERNAL" if public else "INTERNAL",
    )
    comment.save(created_by_id=actor.id)

    _record_activity("comment.activity.created", issue, actor, IssueCommentSerializer(comment).data)
    return {
        "id": str(comment.id),
        "work_item": _issue_identifier(issue),
        "comment_html": comment.comment_html,
        "access": comment.access,
        "visible_to_client": bool(public),
        "visible_to": audience or "somente a equipe",
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


# ---------------------------------------------------------------------------
# Cycle tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_cycles",
    description="Lista os ciclos (sprints) não arquivados de um projeto.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="cycles",
)
def list_cycles(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    cycles = Cycle.objects.filter(project=project_instance, archived_at__isnull=True).order_by("-created_at")
    return {"cycles": [_serialize_cycle(cycle) for cycle in cycles]}


@register_tool(
    name="create_cycle",
    description="Cria um ciclo (sprint) num projeto, com data de início e fim.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Nome do ciclo"),
            "description": _text_property("Descrição em texto simples"),
            "start_date": _date_property("Início ISO (AAAA-MM-DD)"),
            "end_date": _date_property("Fim ISO (AAAA-MM-DD)"),
        },
        "required": ["workspace_slug", "project", "name", "start_date", "end_date"],
        "additionalProperties": False,
    },
    category="cycles",
)
def create_cycle(workspace_slug, project, name, start_date, end_date, description=""):
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    description = _clean_text(description, "description")
    project_instance = _get_project(workspace_slug, project)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start is None or end is None:
        raise MCPToolError("'start_date' e 'end_date' são obrigatórios")
    if end < start:
        raise MCPToolError("'end_date' deve ser depois de 'start_date'")

    actor = _mcp_actor()
    cycle = Cycle(
        name=name,
        description=description,
        project=project_instance,
        start_date=start,
        end_date=end,
        # A cycle needs an owner; the MCP token belongs to the instance, so the bot owns it.
        owned_by=actor,
    )
    cycle.save(created_by_id=actor.id)
    return _serialize_cycle(cycle)


# ---------------------------------------------------------------------------
# Module tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_modules",
    description="Lista os módulos não arquivados de um projeto.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="modules",
)
def list_modules(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    modules = Module.objects.filter(project=project_instance, archived_at__isnull=True).order_by("-created_at")
    return {"modules": [_serialize_module(module) for module in modules]}


@register_tool(
    name="create_module",
    description="Cria um módulo num projeto.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Nome do módulo"),
            "description": _text_property("Descrição em texto simples"),
            "status": {
                "type": "string",
                "enum": list(MODULE_STATUS_CHOICES),
                "description": "Situação do módulo (padrão: planned)",
            },
            "start_date": _date_property("Início ISO (AAAA-MM-DD)"),
            "target_date": _date_property("Prazo ISO (AAAA-MM-DD)"),
        },
        "required": ["workspace_slug", "project", "name"],
        "additionalProperties": False,
    },
    category="modules",
)
def create_module(workspace_slug, project, name, description="", status=None, start_date=None, target_date=None):
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    description = _clean_text(description, "description")
    if status is not None and status not in MODULE_STATUS_CHOICES:
        raise MCPToolError(f"'status' deve ser um destes: {', '.join(MODULE_STATUS_CHOICES)}")
    project_instance = _get_project(workspace_slug, project)
    start = _parse_date(start_date, "start_date")
    target = _parse_date(target_date, "target_date")
    if start and target and target < start:
        raise MCPToolError("'target_date' deve ser depois de 'start_date'")
    if Module.objects.filter(project=project_instance, name=name).exists():
        raise MCPToolError(f"Já existe um módulo chamado '{name}' neste projeto")

    module_kwargs = {
        "name": name,
        "description": description,
        "project": project_instance,
        "start_date": start,
        "target_date": target,
    }
    if status is not None:
        module_kwargs["status"] = status

    try:
        module = Module.objects.create(**module_kwargs)
    except IntegrityError:
        raise MCPToolError(f"Já existe um módulo chamado '{name}' neste projeto")
    return _serialize_module(module)


# ---------------------------------------------------------------------------
# State tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_states",
    description="Lista os estados (colunas do board) de um projeto, na ordem do board.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="states",
)
def list_states(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    states = State.objects.filter(project=project_instance).order_by("sequence")
    return {"states": [_serialize_state(state) for state in states]}


# ---------------------------------------------------------------------------
# Label tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_labels",
    description="Lista as etiquetas de um projeto.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="labels",
)
def list_labels(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    labels = Label.objects.filter(project=project_instance, parent__isnull=True).order_by("name")
    return {"labels": [_serialize_label(label) for label in labels]}


@register_tool(
    name="create_label",
    description="Cria uma etiqueta num projeto.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Nome da etiqueta"),
            "color": {
                "type": "string",
                "maxLength": 7,
                "description": "Cor hexadecimal, ex.: '#F59E0B' (padrão '#FF6900')",
            },
            "description": _text_property("Descrição em texto simples"),
        },
        "required": ["workspace_slug", "project", "name"],
        "additionalProperties": False,
    },
    category="labels",
)
def create_label(workspace_slug, project, name, color=None, description=""):
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    color = _clean_color(color) if color else "#FF6900"
    description = _clean_text(description, "description")
    project_instance = _get_project(workspace_slug, project)
    if Label.objects.filter(project=project_instance, name__iexact=name).exists():
        raise MCPToolError(f"Já existe uma etiqueta chamada '{name}' neste projeto")
    label = Label.objects.create(
        name=name,
        color=color,
        description=description,
        project=project_instance,
    )
    return _serialize_label(label)


# ---------------------------------------------------------------------------
# Page tools
# ---------------------------------------------------------------------------


def _visible_pages(project_instance):
    """Public pages of the project and the bot's own: people's private pages stay private, as in the app."""
    return Page.objects.filter(projects__id=project_instance.id).filter(Q(access=0) | Q(owned_by=_mcp_actor()))


@register_tool(
    name="list_pages",
    description="Lista as páginas públicas de um projeto (páginas privadas de outras pessoas não aparecem).",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY},
        "required": ["workspace_slug", "project"],
        "additionalProperties": False,
    },
    category="pages",
)
def list_pages(workspace_slug, project):
    project_instance = _get_project(workspace_slug, project)
    pages = _visible_pages(project_instance).filter(archived_at__isnull=True).order_by("-created_at").distinct()
    return {"pages": [_serialize_page(page) for page in pages]}
