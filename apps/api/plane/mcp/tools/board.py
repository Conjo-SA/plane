# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the rest of the board over MCP.

Deleting, archiving, sub-items, relations, links, comments, history, cycles and modules (their
work items), states, labels, pages, project members and the intake (triage). Every write is
recorded in the work item history as the "Assistente (MCP)" bot, the same way the app does it.
"""

# Python imports
import datetime
import json
import math
from urllib.parse import urlparse

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

# Module imports
from plane.db.models import (
    Cycle,
    CycleIssue,
    IntakeIssue,
    Issue,
    IssueActivity,
    IssueComment,
    IssueLink,
    IssueRelation,
    Label,
    Module,
    ModuleIssue,
    ProjectMember,
    ProjectPage,
    State,
    WorkspaceMember,
)
from plane.utils.conjo_state_timeline import build_state_timeline
from plane.mcp.tools.handlers import (
    _CONFIRM_PROPERTY,
    _PROJECT_PROPERTY,
    _WORK_ITEM_PROPERTY,
    _WORKSPACE_SLUG_PROPERTY,
    BULK_CONFIRM_THRESHOLD,
    MAX_COMMENT_HTML_LENGTH,
    MAX_LIST_ITEMS,
    MAX_NAME_LENGTH,
    MODULE_STATUS_CHOICES,
    PRIORITY_CHOICES,
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_MEMBER,
    STATE_GROUP_CHOICES,
    MCPToolError,
    _clean_color,
    _clean_html,
    _clean_text,
    _date_property,
    _get_issue,
    _get_project,
    _html_property,
    _is_uuid,
    _issue_identifier,
    _limit,
    _limit_property,
    _mcp_actor,
    _name_property,
    _parse_date,
    _record_activity,
    _require_confirm,
    _serialize_cycle,
    _serialize_issue,
    _serialize_label,
    _serialize_module,
    _serialize_page,
    _serialize_state,
    _serialize_user,
    _text_property,
    _uuid_list_property,
    _visible_pages,
    _workspace_user,
    issue_prefetch,
)
from plane.mcp.tools.registry import register_tool
from plane.utils.issue_relation_mapper import get_actual_relation, get_inverse_relation

STATE_GROUPS = STATE_GROUP_CHOICES
RELATION_TYPES = (
    "blocking",
    "blocked_by",
    "relates_to",
    "duplicate",
    "start_before",
    "start_after",
    "finish_before",
    "finish_after",
    "implements",
    "implemented_by",
)
# Relations stored with the two work items swapped (the app does the same).
_SWAPPED_RELATIONS = ("blocking", "start_after", "finish_after")
INTAKE_ACTIONS = {"accept": 1, "decline": -1, "snooze": 0, "duplicate": 2}
INTAKE_STATUS_LABELS = {-2: "pending", -1: "declined", 0: "snoozed", 1: "accepted", 2: "duplicate"}
ROLE_CHOICES = {"admin": ROLE_ADMIN, "member": ROLE_MEMBER, "guest": ROLE_GUEST}
MAX_URL_LENGTH = 2000

_CYCLE_ID = {"cycle_id": {"type": "string", "maxLength": 100, "description": "UUID do ciclo (list_cycles)"}}
_MODULE_ID = {"module_id": {"type": "string", "maxLength": 100, "description": "UUID do módulo (list_modules)"}}
_STATE_ID = {"state_id": {"type": "string", "maxLength": 100, "description": "UUID do estado (list_states)"}}
_LABEL_ID = {"label_id": {"type": "string", "maxLength": 100, "description": "UUID da etiqueta (list_labels)"}}
_PAGE_ID = {"page_id": {"type": "string", "maxLength": 100, "description": "UUID da página (list_pages)"}}
_WORK_ITEMS = {
    "work_items": _uuid_list_property("Identificadores (ex.: 'MAN-12') ou UUIDs dos itens, todos do projeto")
}
_COLOR = {"color": {"type": "string", "maxLength": 7, "description": "Cor hexadecimal, ex.: '#3B82F6'"}}


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _as_date(value):
    """Cycle dates are datetimes in the database and dates when typed: compare them as dates."""
    return value.date() if hasattr(value, "date") and callable(value.date) else value


def _get_cycle(project, cycle_id):
    cycle = Cycle.objects.filter(project=project, pk=cycle_id).first() if _is_uuid(cycle_id) else None
    if cycle is None:
        raise MCPToolError(f"O ciclo '{cycle_id}' não existe no projeto '{project.identifier}'")
    return cycle


def _get_module(project, module_id):
    module = Module.objects.filter(project=project, pk=module_id).first() if _is_uuid(module_id) else None
    if module is None:
        raise MCPToolError(f"O módulo '{module_id}' não existe no projeto '{project.identifier}'")
    return module


def _get_state(project, state_id):
    state = State.objects.filter(project=project, pk=state_id).first() if _is_uuid(state_id) else None
    if state is None:
        raise MCPToolError(f"O estado '{state_id}' não existe no projeto '{project.identifier}'")
    return state


def _get_label(project, label_id):
    label = Label.objects.filter(project=project, pk=label_id).first() if _is_uuid(label_id) else None
    if label is None:
        raise MCPToolError(f"A etiqueta '{label_id}' não existe no projeto '{project.identifier}'")
    return label


def _issues_of_project(workspace_slug, project, work_items):
    """Resolve several work items, all of them in ``project``."""
    if not isinstance(work_items, list) or not work_items:
        raise MCPToolError("'work_items' deve ser uma lista não vazia de identificadores ou UUIDs")
    if len(work_items) > MAX_LIST_ITEMS:
        raise MCPToolError(f"No máximo {MAX_LIST_ITEMS} itens por chamada")
    issues = []
    seen = set()
    for item in work_items:
        issue = _get_issue(workspace_slug, item)
        if issue.id not in seen:
            seen.add(issue.id)
            issues.append(issue)
    foreign = [_issue_identifier(issue) for issue in issues if issue.project_id != project.id]
    if foreign:
        raise MCPToolError(f"Itens de outro projeto: {', '.join(foreign)}")
    return issues


def _user_in_workspace(workspace, user_ref):
    """A workspace member (row) by UUID or e-mail."""
    user = _workspace_user(workspace.slug, user_ref)
    return WorkspaceMember.objects.get(workspace=workspace, member=user, is_active=True)


def _comment_payload(comment):
    return {
        "id": str(comment.id),
        "comment_html": comment.comment_html,
        "access": comment.access,
        "visible_to_client": comment.access == "EXTERNAL",
        "from_requester": comment.external_source == "INTAKE_PORTAL",
        "author": (comment.actor.display_name or comment.actor.email) if comment.actor_id else None,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
    }


def _list_issues(queryset):
    return queryset.select_related("project", "state").prefetch_related(*issue_prefetch()).order_by("sequence_id")


# ---------------------------------------------------------------------------
# Work items: delete, archive, sub-items, bulk updates
# ---------------------------------------------------------------------------


@register_tool(
    name="delete_work_item",
    description=(
        "Exclui um item: ele some do board, das buscas e dos relatórios e não há como restaurar pelo app "
        "(IRREVERSÍVEL para o usuário). Registra no histórico. Prefira archive_work_item para itens concluídos. "
        "Exige confirm=true."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, **_CONFIRM_PROPERTY},
        ["workspace_slug", "work_item"],
    ),
    category="work_items",
)
def delete_work_item(workspace_slug, work_item, confirm=False):
    issue = _get_issue(workspace_slug, work_item)
    identifier = _issue_identifier(issue)
    _require_confirm(confirm, f"Excluir {identifier} é irreversível.")
    actor = _mcp_actor()
    issue_id = str(issue.id)
    issue.delete()
    _record_activity("issue.activity.deleted", issue, actor, {"issue_id": issue_id}, {})
    return {"deleted": identifier}


@register_tool(
    name="archive_work_item",
    description=(
        "Arquiva um item (sai do board, mas continua consultável e pode ser desarquivado). Só itens em estado "
        "concluído ou cancelado, como no app. Registra no histórico."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def archive_work_item(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    if issue.archived_at is not None:
        raise MCPToolError(f"{_issue_identifier(issue)} já está arquivado")
    if not issue.state_id or issue.state.group not in ("completed", "cancelled"):
        raise MCPToolError("Só itens em estado concluído ou cancelado podem ser arquivados")
    today = timezone.now().date()
    _record_activity(
        "issue.activity.updated",
        issue,
        _mcp_actor(),
        {"archived_at": str(today), "automation": False},
        {"archived_at": None},
    )
    issue.archived_at = today
    issue.save(update_fields=["archived_at", "updated_at"])
    return {"archived": _issue_identifier(issue), "archived_at": str(today)}


@register_tool(
    name="unarchive_work_item",
    description="Traz de volta ao board um item arquivado. Registra no histórico.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def unarchive_work_item(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    if issue.archived_at is None:
        raise MCPToolError(f"{_issue_identifier(issue)} não está arquivado")
    _record_activity(
        "issue.activity.updated", issue, _mcp_actor(), {"archived_at": None}, {"archived_at": str(issue.archived_at)}
    )
    issue.archived_at = None
    issue.save(update_fields=["archived_at", "updated_at"])
    return {"unarchived": _issue_identifier(issue)}


@register_tool(
    name="list_sub_work_items",
    description="Lista os subitens (filhos) de um item.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_sub_work_items(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    children = _list_issues(Issue.issue_objects.filter(parent=issue))
    return {"parent": _issue_identifier(issue), "sub_work_items": [_serialize_issue(child) for child in children]}


@register_tool(
    name="bulk_update_work_items",
    description=(
        f"Aplica a mesma mudança a vários itens de um projeto (até {MAX_LIST_ITEMS}): estado, prioridade, "
        "responsáveis, etiquetas, datas, ciclo ou módulo. Campos omitidos não mudam; responsáveis e etiquetas "
        "substituem os atuais. cycle_id='' tira os itens do ciclo. Cada item recebe registro no histórico. "
        f"Mais de {BULK_CONFIRM_THRESHOLD} itens exige confirm=true."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_WORK_ITEMS,
            "state_id": {"type": "string", "maxLength": 100, "description": "UUID do novo estado"},
            "priority": {"type": "string", "enum": list(PRIORITY_CHOICES), "description": "Nova prioridade"},
            "assignee_ids": _uuid_list_property("UUIDs dos responsáveis (substitui)"),
            "label_ids": _uuid_list_property("UUIDs das etiquetas (substitui)"),
            "start_date": _date_property("Início ISO; '' limpa"),
            "target_date": _date_property("Prazo ISO; '' limpa"),
            "cycle_id": {
                "type": "string",
                "maxLength": 100,
                "description": "UUID do ciclo, ou '' para tirar do ciclo atual",
            },
            "module_id": {"type": "string", "maxLength": 100, "description": "UUID do módulo onde incluir os itens"},
            "confirm": {
                "type": "boolean",
                "description": f"Obrigatório (true) quando houver mais de {BULK_CONFIRM_THRESHOLD} itens",
            },
        },
        ["workspace_slug", "project", "work_items"],
    ),
    category="work_items",
)
def bulk_update_work_items(
    workspace_slug,
    project,
    work_items,
    state_id=None,
    priority=None,
    assignee_ids=None,
    label_ids=None,
    start_date=None,
    target_date=None,
    cycle_id=None,
    module_id=None,
    confirm=False,
):
    from plane.mcp.tools.handlers import _validate_assignees, _validate_labels, update_work_item

    project_instance = _get_project(workspace_slug, project)
    issues = _issues_of_project(workspace_slug, project_instance, work_items)
    if len(issues) > BULK_CONFIRM_THRESHOLD:
        _require_confirm(confirm, f"A mudança atinge {len(issues)} itens.")
    if priority is not None and priority not in PRIORITY_CHOICES:
        raise MCPToolError(f"'priority' deve ser um destes: {', '.join(PRIORITY_CHOICES)}")
    # Validate every target before changing anything.
    if state_id:
        _get_state(project_instance, state_id)
    _validate_assignees(project_instance, assignee_ids)
    _validate_labels(project_instance, label_ids)
    _parse_date(start_date, "start_date")
    _parse_date(target_date, "target_date")
    if cycle_id:
        _get_cycle(project_instance, cycle_id)
    if module_id:
        _get_module(project_instance, module_id)

    identifiers = [_issue_identifier(issue) for issue in issues]
    fields = {
        "state_id": state_id or None,
        "priority": priority,
        "assignee_ids": assignee_ids,
        "label_ids": label_ids,
        "start_date": start_date,
        "target_date": target_date,
    }
    fields = {key: value for key, value in fields.items() if value is not None}
    if fields:
        for issue in issues:
            update_work_item(workspace_slug, str(issue.id), **fields)
    if cycle_id is not None:
        if cycle_id == "":
            for issue in issues:
                current = CycleIssue.objects.filter(issue=issue).select_related("cycle").first()
                if current is not None:
                    remove_work_item_from_cycle(workspace_slug, project, str(current.cycle_id), str(issue.id))
        else:
            add_work_items_to_cycle(workspace_slug, project, cycle_id, identifiers)
    if module_id:
        add_work_items_to_module(workspace_slug, project, module_id, identifiers)
    return {"updated": identifiers}


# ---------------------------------------------------------------------------
# Relations and links
# ---------------------------------------------------------------------------


def _relations_of(issue):
    relations = []
    rows = IssueRelation.objects.filter(Q(issue=issue) | Q(related_issue=issue)).select_related(
        "issue__project", "related_issue__project"
    )
    for row in rows:
        if row.issue_id == issue.id:
            other, relation = row.related_issue, row.relation_type
        else:
            other, relation = row.issue, get_inverse_relation(row.relation_type)
        if other is None or other.deleted_at is not None:
            continue
        relations.append(
            {"relation_type": relation, "work_item": _issue_identifier(other), "name": other.name, "id": str(other.id)}
        )
    return relations


@register_tool(
    name="list_work_item_relations",
    description="Lista como um item se relaciona com outros (blocking, blocked_by, relates_to, duplicate, ...).",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_work_item_relations(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    return {"work_item": _issue_identifier(issue), "relations": _relations_of(issue)}


@register_tool(
    name="add_work_item_relation",
    description=(
        "Relaciona um item com outro do mesmo workspace (registra no histórico). relation_type é lido a partir "
        "do primeiro item: 'MAN-1 blocking MAN-2' significa que MAN-1 bloqueia MAN-2."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "relation_type": {"type": "string", "enum": list(RELATION_TYPES), "description": "Tipo da relação"},
            "related_work_item": {
                "type": "string",
                "maxLength": 100,
                "description": "Identificador ou UUID do outro item",
            },
        },
        ["workspace_slug", "work_item", "relation_type", "related_work_item"],
    ),
    category="work_items",
)
def add_work_item_relation(workspace_slug, work_item, relation_type, related_work_item):
    if relation_type not in RELATION_TYPES:
        raise MCPToolError(f"'relation_type' deve ser um destes: {', '.join(RELATION_TYPES)}")
    issue = _get_issue(workspace_slug, work_item)
    other = _get_issue(workspace_slug, related_work_item)
    if issue.id == other.id:
        raise MCPToolError("Um item não pode se relacionar consigo mesmo")
    if IssueRelation.objects.filter(Q(issue=issue, related_issue=other) | Q(issue=other, related_issue=issue)).exists():
        raise MCPToolError("Estes itens já estão relacionados; remova a relação antes de trocá-la")
    swapped = relation_type in _SWAPPED_RELATIONS
    actor = _mcp_actor()
    IssueRelation.objects.create(
        issue=other if swapped else issue,
        related_issue=issue if swapped else other,
        relation_type=get_actual_relation(relation_type),
        project_id=issue.project_id,
        workspace_id=issue.workspace_id,
        created_by=actor,
        updated_by=actor,
    )
    _record_activity(
        "issue_relation.activity.created", issue, actor, {"relation_type": relation_type, "issues": [str(other.id)]}
    )
    return {"work_item": _issue_identifier(issue), "relations": _relations_of(issue)}


@register_tool(
    name="remove_work_item_relation",
    description="Remove a relação entre dois itens (registra no histórico).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "related_work_item": {
                "type": "string",
                "maxLength": 100,
                "description": "Identificador ou UUID do outro item",
            },
        },
        ["workspace_slug", "work_item", "related_work_item"],
    ),
    category="work_items",
)
def remove_work_item_relation(workspace_slug, work_item, related_work_item):
    issue = _get_issue(workspace_slug, work_item)
    other = _get_issue(workspace_slug, related_work_item)
    relation = IssueRelation.objects.filter(
        Q(issue=issue, related_issue=other) | Q(issue=other, related_issue=issue)
    ).first()
    if relation is None:
        raise MCPToolError("Estes itens não estão relacionados")
    relation_type = (
        relation.relation_type if relation.issue_id == issue.id else get_inverse_relation(relation.relation_type)
    )
    relation.delete()
    _record_activity(
        "issue_relation.activity.deleted",
        issue,
        _mcp_actor(),
        {"related_issue": str(other.id), "relation_type": relation_type},
        {},
    )
    return {"work_item": _issue_identifier(issue), "relations": _relations_of(issue)}


@register_tool(
    name="list_work_item_links",
    description="Lista os links externos anexados a um item.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_work_item_links(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    links = IssueLink.objects.filter(issue=issue).order_by("created_at")
    return {
        "work_item": _issue_identifier(issue),
        "links": [{"id": str(link.id), "title": link.title, "url": link.url} for link in links],
    }


@register_tool(
    name="get_work_item_state_timeline",
    description=(
        "Tempo que o item passou em cada coluna (estado) do board, em ordem, até ser concluído ou cancelado; "
        "inclui o total por coluna e o tempo desde a criação."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def get_work_item_state_timeline(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    return {"work_item": _issue_identifier(issue), **build_state_timeline(issue)}


@register_tool(
    name="add_work_item_link",
    description="Anexa um link externo (http/https) a um item (registra no histórico).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "url": {"type": "string", "maxLength": MAX_URL_LENGTH, "description": "Endereço http:// ou https://"},
            "title": _name_property("Título do link (opcional)"),
        },
        ["workspace_slug", "work_item", "url"],
    ),
    category="work_items",
)
def add_work_item_link(workspace_slug, work_item, url, title=""):
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc or any(c.isspace() for c in url):
        raise MCPToolError("'url' deve ser um endereço http:// ou https:// válido")
    if len(url) > MAX_URL_LENGTH:
        raise MCPToolError(f"'url' passa do limite de {MAX_URL_LENGTH} caracteres")
    title = _clean_text(title, "title", MAX_NAME_LENGTH)
    issue = _get_issue(workspace_slug, work_item)
    if IssueLink.objects.filter(issue=issue, url=url).exists():
        raise MCPToolError("Este link já está anexado ao item")
    actor = _mcp_actor()
    link = IssueLink(issue=issue, project_id=issue.project_id, url=url, title=title or None)
    link.save(created_by_id=actor.id)
    _record_activity("link.activity.created", issue, actor, {"id": str(link.id), "url": link.url, "title": link.title})
    return {"id": str(link.id), "title": link.title, "url": link.url}


@register_tool(
    name="delete_work_item_link",
    description="Remove um link de um item (registra no histórico).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "link_id": {"type": "string", "maxLength": 100, "description": "UUID do link (list_work_item_links)"},
        },
        ["workspace_slug", "work_item", "link_id"],
    ),
    category="work_items",
)
def delete_work_item_link(workspace_slug, work_item, link_id):
    issue = _get_issue(workspace_slug, work_item)
    link = IssueLink.objects.filter(issue=issue, pk=link_id).first() if _is_uuid(link_id) else None
    if link is None:
        raise MCPToolError(f"O link '{link_id}' não existe em {_issue_identifier(issue)}")
    current = {"id": str(link.id), "url": link.url, "title": link.title}
    link.delete()
    _record_activity("link.activity.deleted", issue, _mcp_actor(), {}, current)
    return {"deleted": link_id}


# ---------------------------------------------------------------------------
# Comments and history
# ---------------------------------------------------------------------------


@register_tool(
    name="list_work_item_comments",
    description=(
        "Lista os comentários de um item, do mais antigo ao mais novo. visible_to_client=true indica resposta "
        "pública (o cliente vê no portal); from_requester=true indica mensagem escrita pelo cliente no portal."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_work_item_comments(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    comments = IssueComment.objects.filter(issue=issue).select_related("actor").order_by("created_at")
    return {"work_item": _issue_identifier(issue), "comments": [_comment_payload(c) for c in comments]}


def _own_comment(issue, comment_id):
    comment = IssueComment.objects.filter(issue=issue, pk=comment_id).first() if _is_uuid(comment_id) else None
    if comment is None:
        raise MCPToolError(f"O comentário '{comment_id}' não existe em {_issue_identifier(issue)}")
    # The MCP only edits what it wrote: people's comments stay theirs.
    if comment.actor_id != _mcp_actor().id:
        raise MCPToolError("Só comentários escritos pelo MCP podem ser alterados ou excluídos por aqui")
    return comment


_COMMENT_ID = {"comment_id": {"type": "string", "maxLength": 100, "description": "UUID do comentário"}}


@register_tool(
    name="update_work_item_comment",
    description=(
        "Edita um comentário escrito pelo MCP (registra no histórico). A visibilidade não muda: se for uma "
        "resposta pública, o cliente passa a ver o texto novo no portal."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            **_COMMENT_ID,
            "comment_html": _html_property("Novo corpo em HTML", MAX_COMMENT_HTML_LENGTH),
        },
        ["workspace_slug", "work_item", "comment_id", "comment_html"],
    ),
    category="work_items",
)
def update_work_item_comment(workspace_slug, work_item, comment_id, comment_html):
    clean = _clean_html(comment_html, "comment_html", MAX_COMMENT_HTML_LENGTH)
    if clean.replace("<p></p>", "").strip() == "":
        raise MCPToolError("'comment_html' é obrigatório")
    issue = _get_issue(workspace_slug, work_item)
    comment = _own_comment(issue, comment_id)
    before = {"id": str(comment.id), "comment_html": comment.comment_html}
    comment.comment_html = clean
    comment.edited_at = timezone.now()
    comment.save(update_fields=["comment_html", "comment_stripped", "edited_at", "updated_at"])
    _record_activity("comment.activity.updated", issue, _mcp_actor(), {"comment_html": clean}, before)
    return _comment_payload(comment)


@register_tool(
    name="delete_work_item_comment",
    description=(
        "Exclui um comentário escrito pelo MCP (registra no histórico). Se era resposta pública, some também do "
        "portal do cliente."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, **_COMMENT_ID},
        ["workspace_slug", "work_item", "comment_id"],
    ),
    category="work_items",
)
def delete_work_item_comment(workspace_slug, work_item, comment_id):
    issue = _get_issue(workspace_slug, work_item)
    comment = _own_comment(issue, comment_id)
    comment.delete()
    _record_activity("comment.activity.deleted", issue, _mcp_actor(), {"comment_id": str(comment_id)}, {})
    return {"deleted": comment_id}


@register_tool(
    name="list_work_item_activity",
    description="Histórico de um item: quem mudou o quê e quando (mais recente primeiro).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "limit": _limit_property(50, 200)},
        ["workspace_slug", "work_item"],
    ),
    category="work_items",
)
def list_work_item_activity(workspace_slug, work_item, limit=50):
    issue = _get_issue(workspace_slug, work_item)
    limit = _limit(limit, 50, 200)
    rows = IssueActivity.objects.filter(issue=issue).select_related("actor").order_by("-created_at")[:limit]
    return {
        "work_item": _issue_identifier(issue),
        "activity": [
            {
                "verb": row.verb,
                "field": row.field,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "actor": (row.actor.display_name or row.actor.email) if row.actor_id else None,
                "at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------


def _cycle_with_progress(cycle):
    data = _serialize_cycle(cycle)
    counts = (
        CycleIssue.objects.filter(cycle=cycle, issue__deleted_at__isnull=True, issue__archived_at__isnull=True)
        .values("issue__state__group")
        .annotate(n=Count("id"))
    )
    by_group = {row["issue__state__group"]: row["n"] for row in counts}
    total = sum(by_group.values())
    done = by_group.get("completed", 0) + by_group.get("cancelled", 0)
    data["progress"] = {"total": total, "done": done, "by_state_group": by_group}
    return data


@register_tool(
    name="retrieve_cycle",
    description="Um ciclo com o progresso (itens por grupo de estado) e seus itens.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_CYCLE_ID},
        ["workspace_slug", "project", "cycle_id"],
    ),
    category="cycles",
)
def retrieve_cycle(workspace_slug, project, cycle_id):
    cycle = _get_cycle(_get_project(workspace_slug, project), cycle_id)
    issues = _list_issues(
        Issue.issue_objects.filter(issue_cycle__cycle=cycle, issue_cycle__deleted_at__isnull=True)
    ).distinct()
    return {**_cycle_with_progress(cycle), "work_items": [_serialize_issue(issue) for issue in issues]}


@register_tool(
    name="update_cycle",
    description="Altera nome, descrição ou datas de um ciclo.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_CYCLE_ID,
            "name": _name_property("Novo nome"),
            "description": _text_property("Nova descrição (texto simples)"),
            "start_date": _date_property("Início ISO (AAAA-MM-DD)"),
            "end_date": _date_property("Fim ISO (AAAA-MM-DD)"),
        },
        ["workspace_slug", "project", "cycle_id"],
    ),
    category="cycles",
)
def update_cycle(workspace_slug, project, cycle_id, name=None, description=None, start_date=None, end_date=None):
    cycle = _get_cycle(_get_project(workspace_slug, project), cycle_id)
    if name is not None:
        cycle.name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if description is not None:
        cycle.description = _clean_text(description, "description")
    if start_date is not None:
        cycle.start_date = _parse_date(start_date, "start_date")
    if end_date is not None:
        cycle.end_date = _parse_date(end_date, "end_date")
    if cycle.start_date and cycle.end_date and _as_date(cycle.end_date) < _as_date(cycle.start_date):
        raise MCPToolError("'end_date' deve ser depois de 'start_date'")
    cycle.save()
    cycle.refresh_from_db()
    return _cycle_with_progress(cycle)


@register_tool(
    name="delete_cycle",
    description=(
        "Exclui um ciclo (IRREVERSÍVEL). Os itens continuam no board, só ficam sem ciclo. Registra no histórico "
        "dos itens. Exige confirm=true."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_CYCLE_ID, **_CONFIRM_PROPERTY},
        ["workspace_slug", "project", "cycle_id"],
    ),
    category="cycles",
)
def delete_cycle(workspace_slug, project, cycle_id, confirm=False):
    cycle = _get_cycle(_get_project(workspace_slug, project), cycle_id)
    _require_confirm(confirm, f"Excluir o ciclo '{cycle.name}' é irreversível.")
    issue_ids = [str(i) for i in CycleIssue.objects.filter(cycle=cycle).values_list("issue_id", flat=True)]
    actor = _mcp_actor()
    name = cycle.name
    with transaction.atomic():
        CycleIssue.objects.filter(cycle=cycle).delete()
        cycle.delete()
    first = Issue.objects.filter(pk__in=issue_ids).first()
    if first is not None:
        _record_activity(
            "cycle.activity.deleted",
            first,
            actor,
            {"cycle_id": str(cycle_id), "cycle_name": name, "issues": issue_ids},
            {},
        )
    return {"deleted": name, "work_items_released": len(issue_ids)}


@register_tool(
    name="add_work_items_to_cycle",
    description=(
        "Coloca itens num ciclo (registra no histórico). Um item fica em um ciclo por vez: os que já estão em "
        "outro ciclo são movidos. Ciclos encerrados não recebem itens."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_CYCLE_ID, **_WORK_ITEMS},
        ["workspace_slug", "project", "cycle_id", "work_items"],
    ),
    category="cycles",
)
def add_work_items_to_cycle(workspace_slug, project, cycle_id, work_items):
    project_instance = _get_project(workspace_slug, project)
    cycle = _get_cycle(project_instance, cycle_id)
    if cycle.end_date and _as_date(cycle.end_date) < timezone.localdate():
        raise MCPToolError("Este ciclo já terminou e não recebe itens")
    issues = _issues_of_project(workspace_slug, project_instance, work_items)
    actor = _mcp_actor()
    created, updated = [], []
    with transaction.atomic():
        for issue in issues:
            current = CycleIssue.objects.filter(issue=issue).first()
            if current is not None:
                if current.cycle_id == cycle.id:
                    continue
                updated.append(
                    {"old_cycle_id": str(current.cycle_id), "new_cycle_id": str(cycle.id), "issue_id": str(issue.id)}
                )
                current.cycle = cycle
                current.save(update_fields=["cycle", "updated_at"])
            else:
                CycleIssue.objects.create(
                    issue=issue, cycle=cycle, project_id=project_instance.id, workspace_id=project_instance.workspace_id
                )
                created.append({"fields": {"cycle": str(cycle.id), "issue": str(issue.id)}})
    if created or updated:
        _record_activity(
            "cycle.activity.created",
            issues[0],
            actor,
            {"cycle_id": str(cycle.id), "issues": [str(issue.id) for issue in issues]},
            {"updated_cycle_issues": updated, "created_cycle_issues": json.dumps(created)},
        )
    return {"cycle": cycle.name, "added": len(created), "moved": len(updated)}


@register_tool(
    name="remove_work_item_from_cycle",
    description="Tira um item de um ciclo (registra no histórico).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_CYCLE_ID, **_WORK_ITEM_PROPERTY},
        ["workspace_slug", "project", "cycle_id", "work_item"],
    ),
    category="cycles",
)
def remove_work_item_from_cycle(workspace_slug, project, cycle_id, work_item):
    project_instance = _get_project(workspace_slug, project)
    cycle = _get_cycle(project_instance, cycle_id)
    issue = _get_issue(workspace_slug, work_item)
    link = CycleIssue.objects.filter(cycle=cycle, issue=issue).first()
    if link is None:
        raise MCPToolError(f"{_issue_identifier(issue)} não está no ciclo '{cycle.name}'")
    link.delete()
    _record_activity(
        "cycle.activity.deleted",
        issue,
        _mcp_actor(),
        {"cycle_id": str(cycle.id), "cycle_name": cycle.name, "issues": [str(issue.id)]},
        {},
    )
    return {"removed": _issue_identifier(issue), "cycle": cycle.name}


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------


@register_tool(
    name="retrieve_module",
    description="Um módulo com seus itens.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_MODULE_ID},
        ["workspace_slug", "project", "module_id"],
    ),
    category="modules",
)
def retrieve_module(workspace_slug, project, module_id):
    module = _get_module(_get_project(workspace_slug, project), module_id)
    issues = _list_issues(
        Issue.issue_objects.filter(issue_module__module=module, issue_module__deleted_at__isnull=True)
    ).distinct()
    return {**_serialize_module(module), "work_items": [_serialize_issue(issue) for issue in issues]}


@register_tool(
    name="update_module",
    description="Altera nome, descrição, situação ou datas de um módulo.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_MODULE_ID,
            "name": _name_property("Novo nome"),
            "description": _text_property("Nova descrição (texto simples)"),
            "status": {"type": "string", "enum": list(MODULE_STATUS_CHOICES), "description": "Situação"},
            "start_date": _date_property("Início ISO (AAAA-MM-DD)"),
            "target_date": _date_property("Prazo ISO (AAAA-MM-DD)"),
        },
        ["workspace_slug", "project", "module_id"],
    ),
    category="modules",
)
def update_module(
    workspace_slug, project, module_id, name=None, description=None, status=None, start_date=None, target_date=None
):
    module = _get_module(_get_project(workspace_slug, project), module_id)
    if status is not None and status not in MODULE_STATUS_CHOICES:
        raise MCPToolError(f"'status' deve ser um destes: {', '.join(MODULE_STATUS_CHOICES)}")
    if name is not None:
        module.name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if description is not None:
        module.description = _clean_text(description, "description")
    if status is not None:
        module.status = status
    if start_date is not None:
        module.start_date = _parse_date(start_date, "start_date")
    if target_date is not None:
        module.target_date = _parse_date(target_date, "target_date")
    if module.start_date and module.target_date and module.target_date < module.start_date:
        raise MCPToolError("'target_date' deve ser depois de 'start_date'")
    try:
        with transaction.atomic():
            module.save()
    except IntegrityError:
        raise MCPToolError(f"Já existe um módulo chamado '{module.name}' neste projeto")
    return _serialize_module(module)


@register_tool(
    name="delete_module",
    description=(
        "Exclui um módulo (IRREVERSÍVEL). Os itens continuam no board. Registra no histórico dos itens. "
        "Exige confirm=true."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_MODULE_ID, **_CONFIRM_PROPERTY},
        ["workspace_slug", "project", "module_id"],
    ),
    category="modules",
)
def delete_module(workspace_slug, project, module_id, confirm=False):
    module = _get_module(_get_project(workspace_slug, project), module_id)
    _require_confirm(confirm, f"Excluir o módulo '{module.name}' é irreversível.")
    links = list(ModuleIssue.objects.filter(module=module).select_related("issue"))
    actor = _mcp_actor()
    name = module.name
    with transaction.atomic():
        ModuleIssue.objects.filter(module=module).delete()
        module.delete()
    for link in links:
        _record_activity(
            "module.activity.deleted", link.issue, actor, {"module_id": str(module_id)}, {"module_name": name}
        )
    return {"deleted": name, "work_items_released": len(links)}


@register_tool(
    name="add_work_items_to_module",
    description="Inclui itens num módulo (um item pode estar em vários módulos). Registra no histórico.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_MODULE_ID, **_WORK_ITEMS},
        ["workspace_slug", "project", "module_id", "work_items"],
    ),
    category="modules",
)
def add_work_items_to_module(workspace_slug, project, module_id, work_items):
    project_instance = _get_project(workspace_slug, project)
    module = _get_module(project_instance, module_id)
    issues = _issues_of_project(workspace_slug, project_instance, work_items)
    actor = _mcp_actor()
    added = 0
    for issue in issues:
        _, created = ModuleIssue.objects.get_or_create(
            module=module,
            issue=issue,
            defaults={"project_id": project_instance.id, "workspace_id": project_instance.workspace_id},
        )
        if created:
            added += 1
            _record_activity("module.activity.created", issue, actor, {"module_id": str(module.id)})
    return {"module": module.name, "added": added}


@register_tool(
    name="remove_work_item_from_module",
    description="Tira um item de um módulo (registra no histórico).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_MODULE_ID, **_WORK_ITEM_PROPERTY},
        ["workspace_slug", "project", "module_id", "work_item"],
    ),
    category="modules",
)
def remove_work_item_from_module(workspace_slug, project, module_id, work_item):
    module = _get_module(_get_project(workspace_slug, project), module_id)
    issue = _get_issue(workspace_slug, work_item)
    link = ModuleIssue.objects.filter(module=module, issue=issue).first()
    if link is None:
        raise MCPToolError(f"{_issue_identifier(issue)} não está no módulo '{module.name}'")
    link.delete()
    _record_activity(
        "module.activity.deleted", issue, _mcp_actor(), {"module_id": str(module.id)}, {"module_name": module.name}
    )
    return {"removed": _issue_identifier(issue), "module": module.name}


# ---------------------------------------------------------------------------
# States and labels
# ---------------------------------------------------------------------------


@register_tool(
    name="create_state",
    description="Cria um estado (coluna do board) num projeto, no fim da ordem.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Nome do estado"),
            "group": {"type": "string", "enum": list(STATE_GROUPS), "description": "Grupo do estado"},
            **_COLOR,
            "description": _text_property("Descrição em texto simples"),
        },
        ["workspace_slug", "project", "name", "group"],
    ),
    category="states",
)
def create_state(workspace_slug, project, name, group, color="#60646C", description=""):
    if group not in STATE_GROUPS:
        raise MCPToolError(f"'group' deve ser um destes: {', '.join(STATE_GROUPS)}")
    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    color = _clean_color(color) if color else "#60646C"
    description = _clean_text(description, "description")
    project_instance = _get_project(workspace_slug, project)
    if State.objects.filter(project=project_instance, name__iexact=name).exists():
        raise MCPToolError(f"Já existe um estado chamado '{name}' neste projeto")
    last = State.objects.filter(project=project_instance).order_by("-sequence").first()
    state = State.objects.create(
        name=name,
        group=group,
        color=color,
        description=description,
        project=project_instance,
        sequence=(last.sequence + 15000) if last else 15000,
    )
    return _serialize_state(state)


@register_tool(
    name="update_state",
    description=("Renomeia, muda a cor, o grupo ou a ordem de um estado, ou o torna o estado padrão dos itens novos."),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_STATE_ID,
            "name": _name_property("Novo nome"),
            "group": {"type": "string", "enum": list(STATE_GROUPS), "description": "Novo grupo"},
            **_COLOR,
            "sequence": {"type": "number", "minimum": 0, "description": "Ordem no board (menor vem antes)"},
            "default": {"type": "boolean", "description": "true torna este o estado padrão"},
        },
        ["workspace_slug", "project", "state_id"],
    ),
    category="states",
)
def update_state(workspace_slug, project, state_id, name=None, group=None, color=None, sequence=None, default=None):
    project_instance = _get_project(workspace_slug, project)
    state = _get_state(project_instance, state_id)
    if group is not None and group not in STATE_GROUPS:
        raise MCPToolError(f"'group' deve ser um destes: {', '.join(STATE_GROUPS)}")
    if name is not None:
        name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
        if State.objects.filter(project=project_instance, name__iexact=name).exclude(pk=state.pk).exists():
            raise MCPToolError(f"Já existe um estado chamado '{name}' neste projeto")
        state.name = name
    if group is not None:
        state.group = group
    if color is not None:
        state.color = _clean_color(color)
    if sequence is not None:
        sequence = float(sequence)
        if not math.isfinite(sequence) or sequence < 0:
            raise MCPToolError("'sequence' deve ser um número positivo")
        state.sequence = sequence
    if default is False and state.default:
        raise MCPToolError("Escolha outro estado como padrão em vez de desmarcar este")
    with transaction.atomic():
        if default is True:
            State.objects.filter(project=project_instance, default=True).exclude(pk=state.pk).update(default=False)
            state.default = True
            project_instance.default_state = state
            project_instance.save(update_fields=["default_state", "updated_at"])
        state.save()
    return _serialize_state(state)


@register_tool(
    name="delete_state",
    description=(
        "Exclui um estado (IRREVERSÍVEL). Recusado para o estado padrão ou enquanto houver itens nele (mova-os "
        "antes). Exige confirm=true."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_STATE_ID, **_CONFIRM_PROPERTY},
        ["workspace_slug", "project", "state_id"],
    ),
    category="states",
)
def delete_state(workspace_slug, project, state_id, confirm=False):
    state = _get_state(_get_project(workspace_slug, project), state_id)
    if state.default:
        raise MCPToolError("O estado padrão não pode ser excluído; torne outro estado o padrão antes")
    in_use = Issue.objects.filter(state=state).count()
    if in_use:
        raise MCPToolError(f"{in_use} item(ns) ainda estão neste estado; mova-os para outro estado antes")
    _require_confirm(confirm, f"Excluir o estado '{state.name}' é irreversível.")
    name = state.name
    state.delete()
    return {"deleted": name}


@register_tool(
    name="update_label",
    description="Renomeia, muda a cor ou a descrição de uma etiqueta.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_LABEL_ID,
            "name": _name_property("Novo nome"),
            **_COLOR,
            "description": _text_property("Nova descrição (texto simples)"),
        },
        ["workspace_slug", "project", "label_id"],
    ),
    category="labels",
)
def update_label(workspace_slug, project, label_id, name=None, color=None, description=None):
    project_instance = _get_project(workspace_slug, project)
    label = _get_label(project_instance, label_id)
    if name is not None:
        name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
        if Label.objects.filter(project=project_instance, name__iexact=name).exclude(pk=label.pk).exists():
            raise MCPToolError(f"Já existe uma etiqueta chamada '{name}' neste projeto")
        label.name = name
    if color is not None:
        label.color = _clean_color(color)
    if description is not None:
        label.description = _clean_text(description, "description")
    label.save()
    return _serialize_label(label)


@register_tool(
    name="delete_label",
    description=(
        "Exclui uma etiqueta (IRREVERSÍVEL): ela sai de todos os itens que a tinham e, se for etiqueta de "
        "cliente, o vínculo com o cliente também deixa de valer. Exige confirm=true."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_LABEL_ID, **_CONFIRM_PROPERTY},
        ["workspace_slug", "project", "label_id"],
    ),
    category="labels",
)
def delete_label(workspace_slug, project, label_id, confirm=False):
    label = _get_label(_get_project(workspace_slug, project), label_id)
    _require_confirm(confirm, f"Excluir a etiqueta '{label.name}' é irreversível.")
    name = label.name
    label.delete()
    return {"deleted": name}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _get_page(project_instance, page_id):
    page = _visible_pages(project_instance).filter(pk=page_id).first() if _is_uuid(page_id) else None
    if page is None:
        raise MCPToolError(f"A página '{page_id}' não existe no projeto '{project_instance.identifier}'")
    return page


@register_tool(
    name="retrieve_page",
    description="Uma página pública do projeto com o conteúdo (HTML).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_PAGE_ID},
        ["workspace_slug", "project", "page_id"],
    ),
    category="pages",
)
def retrieve_page(workspace_slug, project, page_id):
    page = _get_page(_get_project(workspace_slug, project), page_id)
    return {**_serialize_page(page), "description_html": page.description_html}


@register_tool(
    name="create_page",
    description=(
        "Cria uma página no projeto, com conteúdo HTML opcional (sanitizado como no app). Páginas públicas são "
        "vistas por todos os membros do projeto; privadas, só pelo MCP."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Título da página"),
            "description_html": _html_property("Conteúdo em HTML"),
            "access": {"type": "string", "enum": ["public", "private"], "description": "Padrão: public"},
        },
        ["workspace_slug", "project", "name"],
    ),
    category="pages",
)
def create_page(workspace_slug, project, name, description_html="", access="public"):
    from plane.db.models import Page

    name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
    if access not in ("public", "private"):
        raise MCPToolError("'access' deve ser public ou private")
    content = _clean_html(description_html)
    project_instance = _get_project(workspace_slug, project)
    actor = _mcp_actor()
    with transaction.atomic():
        page = Page(
            name=name,
            description_html=content,
            workspace_id=project_instance.workspace_id,
            owned_by=actor,
            access=1 if access == "private" else 0,
        )
        page.save(created_by_id=actor.id)
        ProjectPage.objects.create(page=page, project=project_instance, workspace_id=project_instance.workspace_id)
    return {**_serialize_page(page), "description_html": page.description_html}


@register_tool(
    name="update_page",
    description=(
        "Renomeia uma página ou substitui o conteúdo (HTML sanitizado). Substituir o conteúdo descarta o "
        "documento atual: não use enquanto alguém edita a página. Páginas bloqueadas ou arquivadas são recusadas."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_PAGE_ID,
            "name": _name_property("Novo título"),
            "description_html": _html_property("Novo conteúdo em HTML (substitui o atual)"),
        },
        ["workspace_slug", "project", "page_id"],
    ),
    category="pages",
)
def update_page(workspace_slug, project, page_id, name=None, description_html=None):
    page = _get_page(_get_project(workspace_slug, project), page_id)
    if page.is_locked:
        raise MCPToolError("Esta página está bloqueada")
    if page.archived_at is not None:
        raise MCPToolError("Esta página está arquivada")
    fields = ["updated_at"]
    if name is not None:
        page.name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
        fields.append("name")
    if description_html is not None:
        page.description_html = _clean_html(description_html)
        # The editor rebuilds its document from the HTML when the binary is empty.
        page.description_binary = None
        page.description_json = {}
        fields += ["description_html", "description_binary", "description_json"]
    page.save(update_fields=fields)
    return {**_serialize_page(page), "description_html": page.description_html}


# ---------------------------------------------------------------------------
# Project settings
# ---------------------------------------------------------------------------


@register_tool(
    name="update_project",
    description=(
        "Altera nome, descrição ou emoji de um projeto. O identificador (usado nas chaves dos itens) é mantido."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": _name_property("Novo nome"),
            "description": _text_property("Nova descrição (texto simples)"),
            "emoji": {
                "type": "string",
                "maxLength": 16,
                "description": "Código numérico do emoji, ex.: '128640'; '' remove",
            },
        },
        ["workspace_slug", "project"],
    ),
    category="projects",
)
def update_project(workspace_slug, project, name=None, description=None, emoji=None):
    from plane.db.models import Project
    from plane.mcp.tools.handlers import _serialize_project

    project_instance = _get_project(workspace_slug, project)
    if name is not None:
        name = _clean_text(name, "name", MAX_NAME_LENGTH, required=True)
        if (
            Project.objects.filter(workspace_id=project_instance.workspace_id, name__iexact=name)
            .exclude(pk=project_instance.pk)
            .exists()
        ):
            raise MCPToolError(f"Já existe um projeto chamado '{name}'")
        project_instance.name = name
    if description is not None:
        project_instance.description = _clean_text(description, "description")
    if emoji is not None:
        emoji = emoji.strip()
        if emoji and not emoji.isdigit():
            raise MCPToolError("'emoji' deve ser o código numérico do emoji, ex.: '128640'")
        project_instance.emoji = emoji or None
    project_instance.save()
    return _serialize_project(project_instance)


# ---------------------------------------------------------------------------
# Project members
# ---------------------------------------------------------------------------

_MEMBER = {"member": {"type": "string", "maxLength": 254, "description": "E-mail ou UUID da pessoa"}}


@register_tool(
    name="add_project_member",
    description=(
        "Adiciona um membro do workspace a um projeto, ou muda o papel dele lá (admin, member ou guest). Mesmas "
        "regras do app: o papel não pode ser maior que o do workspace, e administradores do workspace entram "
        "como admin. Convidados (guest) não podem ser responsáveis por itens."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            **_MEMBER,
            "role": {"type": "string", "enum": list(ROLE_CHOICES), "description": "Papel no projeto"},
        },
        ["workspace_slug", "project", "member", "role"],
    ),
    category="members",
)
def add_project_member(workspace_slug, project, member, role):
    from plane.db.models import ProjectUserProperty

    if role not in ROLE_CHOICES:
        raise MCPToolError(f"'role' deve ser um destes: {', '.join(ROLE_CHOICES)}")
    project_instance = _get_project(workspace_slug, project)
    workspace_member = _user_in_workspace(project_instance.workspace, member)
    role_value = ROLE_CHOICES[role]
    if role_value > workspace_member.role:
        raise MCPToolError("O papel no projeto não pode ser maior que o papel da pessoa no workspace")
    if workspace_member.role == ROLE_ADMIN and role_value < ROLE_ADMIN:
        raise MCPToolError("Administradores do workspace entram no projeto como admin")
    project_member = ProjectMember.objects.filter(project=project_instance, member=workspace_member.member).first()
    if project_member is None:
        project_member = ProjectMember.objects.create(
            project=project_instance, member=workspace_member.member, role=role_value, is_active=True
        )
    else:
        if project_member.is_active and project_member.role == ROLE_ADMIN and role_value < ROLE_ADMIN:
            admins = ProjectMember.objects.filter(project=project_instance, role=ROLE_ADMIN, is_active=True).count()
            if admins <= 1:
                raise MCPToolError("Esta pessoa é a última administradora do projeto; promova outra antes")
        project_member.role = role_value
        project_member.is_active = True
        project_member.save(update_fields=["role", "is_active", "updated_at"])
    ProjectUserProperty.objects.get_or_create(
        project=project_instance, user=workspace_member.member, workspace_id=project_instance.workspace_id
    )
    return {
        **_serialize_user(workspace_member.member),
        "role": role,
        "project": project_instance.identifier,
    }


@register_tool(
    name="remove_project_member",
    description=(
        "Remove uma pessoa do projeto (ela perde o acesso; itens e histórico ficam). A última pessoa "
        "administradora não pode ser removida. Exige confirm=true."
    ),
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, **_MEMBER, **_CONFIRM_PROPERTY},
        ["workspace_slug", "project", "member"],
    ),
    category="members",
)
def remove_project_member(workspace_slug, project, member, confirm=False):
    project_instance = _get_project(workspace_slug, project)
    workspace_member = _user_in_workspace(project_instance.workspace, member)
    project_member = ProjectMember.objects.filter(
        project=project_instance, member=workspace_member.member, is_active=True
    ).first()
    if project_member is None:
        raise MCPToolError(f"'{member}' não é membro do projeto '{project_instance.identifier}'")
    if project_member.role == ROLE_ADMIN:
        admins = ProjectMember.objects.filter(project=project_instance, role=ROLE_ADMIN, is_active=True).count()
        if admins <= 1:
            raise MCPToolError("Esta pessoa é a última administradora do projeto")
    _require_confirm(confirm, f"Remover {workspace_member.member.email} do projeto tira o acesso dela.")
    project_member.is_active = False
    project_member.save(update_fields=["is_active", "updated_at"])
    return {"removed": workspace_member.member.email, "project": project_instance.identifier}


# ---------------------------------------------------------------------------
# Intake (triage)
# ---------------------------------------------------------------------------


@register_tool(
    name="list_intake_items",
    description=(
        "Pedidos na Entrada de um projeto, vindos do portal do cliente ou criados pela equipe. status: pending "
        "(padrão), snoozed, accepted, declined, duplicate ou all."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "status": {
                "type": "string",
                "enum": ["pending", "snoozed", "accepted", "declined", "duplicate", "all"],
                "description": "Situação na Entrada (padrão pending)",
            },
            "limit": _limit_property(50, 200),
        },
        ["workspace_slug", "project"],
    ),
    category="intake",
)
def list_intake_items(workspace_slug, project, status="pending", limit=50):
    from plane.db.models import IntakePortalBudget

    project_instance = _get_project(workspace_slug, project)
    limit = _limit(limit, 50, 200)
    queryset = IntakeIssue.objects.filter(project=project_instance, issue__deleted_at__isnull=True).select_related(
        "issue", "issue__project"
    )
    if status and status != "all":
        codes = {label: code for code, label in INTAKE_STATUS_LABELS.items()}
        if status not in codes:
            raise MCPToolError("'status' deve ser pending, snoozed, accepted, declined, duplicate ou all")
        queryset = queryset.filter(status=codes[status])
    items = list(queryset.order_by("-created_at")[:limit])
    budgets = {
        budget.issue_id: budget
        for budget in IntakePortalBudget.objects.filter(issue_id__in=[item.issue_id for item in items])
    }
    return {
        "intake_items": [
            {
                "work_item": _issue_identifier(item.issue),
                "id": str(item.issue_id),
                "name": item.issue.name,
                "priority": item.issue.priority,
                "status": INTAKE_STATUS_LABELS.get(item.status, item.status),
                "source": item.source,
                "requester_email": item.source_email,
                "requester_name": (item.extra or {}).get("requester_name") or None,
                "hours_estimate_status": budgets[item.issue_id].status if item.issue_id in budgets else None,
                "snoozed_till": item.snoozed_till.isoformat() if item.snoozed_till else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]
    }


def _parse_snooze(value):
    text = str(value or "").strip()
    try:
        if "T" in text:
            moment = datetime.datetime.fromisoformat(text)
            if timezone.is_naive(moment):
                from plane.utils.conjo_billing import BILLING_TZ

                moment = timezone.make_aware(moment, BILLING_TZ)
        else:
            from plane.utils.conjo_billing import BILLING_TZ

            day = datetime.date.fromisoformat(text[:10])
            moment = timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)), BILLING_TZ)
    except ValueError:
        raise MCPToolError("'snoozed_till' deve ser uma data (AAAA-MM-DD) ou data-hora ISO")
    if moment <= timezone.now():
        raise MCPToolError("'snoozed_till' deve estar no futuro")
    return moment


@register_tool(
    name="triage_intake_item",
    description=(
        "Decide um pedido da Entrada (registra no histórico): accept (vai para o board no estado padrão), "
        "decline (recusa), snooze (adia até uma data) ou duplicate (marca como duplicado de outro item do "
        "projeto). Em chamados do portal o cliente é avisado por e-mail."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "action": {"type": "string", "enum": list(INTAKE_ACTIONS), "description": "Decisão"},
            "snoozed_till": {
                "type": "string",
                "maxLength": 40,
                "description": "Para snooze: data (AAAA-MM-DD, vale 9h de Brasília) ou data-hora ISO",
            },
            "duplicate_of": {
                "type": "string",
                "maxLength": 100,
                "description": "Para duplicate: identificador ou UUID do item original (mesmo projeto)",
            },
        },
        ["workspace_slug", "work_item", "action"],
    ),
    category="intake",
)
def triage_intake_item(workspace_slug, work_item, action, snoozed_till=None, duplicate_of=None):
    from django.core.serializers.json import DjangoJSONEncoder

    from plane.app.serializers import IntakeIssueSerializer

    if action not in INTAKE_ACTIONS:
        raise MCPToolError(f"'action' deve ser um destes: {', '.join(INTAKE_ACTIONS)}")
    issue = _get_issue(workspace_slug, work_item)
    intake_issue = IntakeIssue.objects.filter(issue=issue).first()
    if intake_issue is None:
        raise MCPToolError(f"{_issue_identifier(issue)} não veio da Entrada")
    data = {"status": INTAKE_ACTIONS[action]}
    if action == "snooze":
        if not snoozed_till:
            raise MCPToolError("'snoozed_till' é obrigatório para adiar")
        data["snoozed_till"] = _parse_snooze(snoozed_till).isoformat()
    if action == "duplicate":
        if not duplicate_of:
            raise MCPToolError("'duplicate_of' é obrigatório para marcar como duplicado")
        original = _get_issue(workspace_slug, duplicate_of)
        if original.id == issue.id:
            raise MCPToolError("Um pedido não pode ser duplicado de si mesmo")
        if original.project_id != issue.project_id:
            raise MCPToolError("O item original precisa ser do mesmo projeto")
        data["duplicate_to"] = str(original.id)
    before = json.dumps(IntakeIssueSerializer(intake_issue).data, cls=DjangoJSONEncoder)
    serializer = IntakeIssueSerializer(intake_issue, data=data, partial=True)
    if not serializer.is_valid():
        raise MCPToolError(f"Triagem inválida: {serializer.errors}")
    serializer.save()
    _record_activity("intake.activity.created", issue, _mcp_actor(), data, json.loads(before), intake=intake_issue.id)
    intake_issue.refresh_from_db()
    issue.refresh_from_db()
    return {
        "work_item": _issue_identifier(issue),
        "status": INTAKE_STATUS_LABELS.get(intake_issue.status, intake_issue.status),
        "state_id": str(issue.state_id) if issue.state_id else None,
    }
