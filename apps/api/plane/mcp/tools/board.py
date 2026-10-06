# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the rest of the board over MCP.

Deleting, archiving, sub-items, relations, links, comments, history, cycles and modules (their
work items), states, labels, pages, project members and the intake (triage). Every write is
recorded in the work item history as the "Assistente (MCP)" bot, the same way the app does it.
"""

# Python imports
import json

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
    Page,
    ProjectMember,
    ProjectPage,
    State,
    WorkspaceMember,
)
from plane.mcp.tools.handlers import (
    _PROJECT_PROPERTY,
    _WORK_ITEM_PROPERTY,
    _WORKSPACE_SLUG_PROPERTY,
    MODULE_STATUS_CHOICES,
    MCPToolError,
    _get_issue,
    _get_project,
    _issue_identifier,
    _mcp_actor,
    _parse_date,
    _record_activity,
    _serialize_cycle,
    _serialize_issue,
    _serialize_label,
    _serialize_module,
    _serialize_page,
    _serialize_state,
    _serialize_user,
    _is_uuid,
)
from plane.mcp.tools.registry import register_tool
from plane.utils.issue_relation_mapper import get_actual_relation, get_inverse_relation

STATE_GROUPS = ("backlog", "unstarted", "started", "completed", "cancelled")
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
ROLE_CHOICES = {"admin": 20, "member": 15, "guest": 5}


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _as_date(value):
    """Cycle dates are datetimes in the database and dates when typed: compare them as dates."""
    return value.date() if hasattr(value, "date") and callable(value.date) else value


def _get_cycle(project, cycle_id):
    cycle = Cycle.objects.filter(project=project, pk=cycle_id).first() if _is_uuid(cycle_id) else None
    if cycle is None:
        raise MCPToolError(f"Cycle '{cycle_id}' does not exist in project '{project.identifier}'")
    return cycle


def _get_module(project, module_id):
    module = Module.objects.filter(project=project, pk=module_id).first() if _is_uuid(module_id) else None
    if module is None:
        raise MCPToolError(f"Module '{module_id}' does not exist in project '{project.identifier}'")
    return module


def _get_state(project, state_id):
    state = State.objects.filter(project=project, pk=state_id).first() if _is_uuid(state_id) else None
    if state is None:
        raise MCPToolError(f"State '{state_id}' does not exist in project '{project.identifier}'")
    return state


def _get_label(project, label_id):
    label = Label.objects.filter(project=project, pk=label_id).first() if _is_uuid(label_id) else None
    if label is None:
        raise MCPToolError(f"Label '{label_id}' does not exist in project '{project.identifier}'")
    return label


def _issues_of_project(workspace_slug, project, work_items):
    """Resolve several work items, all of them in ``project``."""
    if not isinstance(work_items, list) or not work_items:
        raise MCPToolError("'work_items' must be a non-empty list of identifiers or UUIDs")
    if len(work_items) > 100:
        raise MCPToolError("At most 100 work items per call")
    issues = [_get_issue(workspace_slug, item) for item in work_items]
    foreign = [_issue_identifier(issue) for issue in issues if issue.project_id != project.id]
    if foreign:
        raise MCPToolError(f"Work items from another project: {', '.join(foreign)}")
    return issues


def _user_in_workspace(workspace, user_ref):
    """A workspace member by UUID or e-mail."""
    members = WorkspaceMember.objects.filter(workspace=workspace, is_active=True).select_related("member")
    if _is_uuid(user_ref):
        member = members.filter(member_id=user_ref).first()
    else:
        member = members.filter(member__email__iexact=str(user_ref).strip()).first()
    if member is None:
        raise MCPToolError(f"'{user_ref}' is not an active member of workspace '{workspace.slug}'")
    return member


def _comment_payload(comment):
    return {
        "id": str(comment.id),
        "comment_html": comment.comment_html,
        "access": comment.access,
        "author": (comment.actor.display_name or comment.actor.email) if comment.actor_id else None,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Work items: delete, archive, sub-items, bulk updates
# ---------------------------------------------------------------------------


@register_tool(
    name="delete_work_item",
    description="Delete a work item (it goes to the project's trash and can be restored by an admin).",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def delete_work_item(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    identifier = _issue_identifier(issue)
    actor = _mcp_actor()
    issue_id = str(issue.id)
    issue.delete()
    _record_activity("issue.activity.deleted", issue, actor, {"issue_id": issue_id}, {})
    return {"deleted": identifier}


@register_tool(
    name="archive_work_item",
    description=(
        "Archive a work item. Only items in a completed or cancelled state can be archived (same rule as the app)."
    ),
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def archive_work_item(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    if issue.archived_at is not None:
        raise MCPToolError(f"{_issue_identifier(issue)} is already archived")
    if not issue.state_id or issue.state.group not in ("completed", "cancelled"):
        raise MCPToolError("Only work items in a completed or cancelled state can be archived")
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
    description="Bring an archived work item back to the board.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def unarchive_work_item(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    if issue.archived_at is None:
        raise MCPToolError(f"{_issue_identifier(issue)} is not archived")
    _record_activity(
        "issue.activity.updated", issue, _mcp_actor(), {"archived_at": None}, {"archived_at": str(issue.archived_at)}
    )
    issue.archived_at = None
    issue.save(update_fields=["archived_at", "updated_at"])
    return {"unarchived": _issue_identifier(issue)}


@register_tool(
    name="list_sub_work_items",
    description="List the sub-work items (children) of a work item.",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_sub_work_items(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    children = (
        Issue.issue_objects.filter(parent=issue)
        .select_related("project", "state")
        .prefetch_related("assignees", "labels")
        .order_by("sequence_id")
    )
    return {"parent": _issue_identifier(issue), "sub_work_items": [_serialize_issue(child) for child in children]}


@register_tool(
    name="bulk_update_work_items",
    description=(
        "Apply the same change to several work items of one project at once (up to 100): state, priority, "
        "assignees, labels, dates, cycle or module. Fields left out are not changed. Use an empty string in "
        "cycle_id/module_id to take the items out of their cycle/module."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "work_items": {"type": "array", "items": {"type": "string"}, "description": "Identifiers or UUIDs"},
            "state_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["urgent", "high", "medium", "low", "none"]},
            "assignee_ids": {"type": "array", "items": {"type": "string"}},
            "label_ids": {"type": "array", "items": {"type": "string"}},
            "start_date": {"type": "string"},
            "target_date": {"type": "string"},
            "cycle_id": {"type": "string", "description": "Cycle UUID, or '' to remove from the current cycle"},
            "module_id": {"type": "string", "description": "Module UUID to add the items to"},
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
):
    from plane.mcp.tools.handlers import update_work_item

    project_instance = _get_project(workspace_slug, project)
    issues = _issues_of_project(workspace_slug, project_instance, work_items)
    if state_id:
        _get_state(project_instance, state_id)
    identifiers = [_issue_identifier(issue) for issue in issues]
    fields = {
        "state_id": state_id,
        "priority": priority,
        "assignee_ids": assignee_ids,
        "label_ids": label_ids,
        "start_date": start_date,
        "target_date": target_date,
    }
    if any(value is not None for value in fields.values()):
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
        relations.append(
            {"relation_type": relation, "work_item": _issue_identifier(other), "name": other.name, "id": str(other.id)}
        )
    return relations


@register_tool(
    name="list_work_item_relations",
    description="List how a work item relates to others (blocking, blocked_by, relates_to, duplicate, ...).",
    input_schema=_schema({**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY}, ["workspace_slug", "work_item"]),
    category="work_items",
)
def list_work_item_relations(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    return {"work_item": _issue_identifier(issue), "relations": _relations_of(issue)}


@register_tool(
    name="add_work_item_relation",
    description=(
        "Relate a work item to another one of the same workspace. relation_type reads from the first item: "
        "'MAN-1 blocking MAN-2' means MAN-1 blocks MAN-2."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "relation_type": {"type": "string", "enum": list(RELATION_TYPES)},
            "related_work_item": {"type": "string", "description": "Identifier or UUID of the other work item"},
        },
        ["workspace_slug", "work_item", "relation_type", "related_work_item"],
    ),
    category="work_items",
)
def add_work_item_relation(workspace_slug, work_item, relation_type, related_work_item):
    if relation_type not in RELATION_TYPES:
        raise MCPToolError(f"relation_type must be one of {', '.join(RELATION_TYPES)}")
    issue = _get_issue(workspace_slug, work_item)
    other = _get_issue(workspace_slug, related_work_item)
    if issue.id == other.id:
        raise MCPToolError("A work item cannot be related to itself")
    if IssueRelation.objects.filter(Q(issue=issue, related_issue=other) | Q(issue=other, related_issue=issue)).exists():
        raise MCPToolError("These work items are already related; remove the relation first to change it")
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
    description="Remove the relation between two work items.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "related_work_item": {"type": "string"}},
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
        raise MCPToolError("These work items are not related")
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
    description="List the external links attached to a work item.",
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
    name="add_work_item_link",
    description="Attach an external link (http/https) to a work item.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "url": {"type": "string"}, "title": {"type": "string"}},
        ["workspace_slug", "work_item", "url"],
    ),
    category="work_items",
)
def add_work_item_link(workspace_slug, work_item, url, title=""):
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise MCPToolError("'url' must start with http:// or https://")
    issue = _get_issue(workspace_slug, work_item)
    if IssueLink.objects.filter(issue=issue, url=url).exists():
        raise MCPToolError("This link is already attached to the work item")
    actor = _mcp_actor()
    link = IssueLink(issue=issue, project_id=issue.project_id, url=url[:2000], title=(title or "")[:255] or None)
    link.save(created_by_id=actor.id)
    _record_activity("link.activity.created", issue, actor, {"id": str(link.id), "url": link.url, "title": link.title})
    return {"id": str(link.id), "title": link.title, "url": link.url}


@register_tool(
    name="delete_work_item_link",
    description="Remove a link from a work item.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "link_id": {"type": "string"}},
        ["workspace_slug", "work_item", "link_id"],
    ),
    category="work_items",
)
def delete_work_item_link(workspace_slug, work_item, link_id):
    issue = _get_issue(workspace_slug, work_item)
    link = IssueLink.objects.filter(issue=issue, pk=link_id).first() if _is_uuid(link_id) else None
    if link is None:
        raise MCPToolError(f"Link '{link_id}' does not exist on {_issue_identifier(issue)}")
    current = {"id": str(link.id), "url": link.url, "title": link.title}
    link.delete()
    _record_activity("link.activity.deleted", issue, _mcp_actor(), {}, current)
    return {"deleted": link_id}


# ---------------------------------------------------------------------------
# Comments and history
# ---------------------------------------------------------------------------


@register_tool(
    name="list_work_item_comments",
    description="List the comments of a work item, oldest first.",
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
        raise MCPToolError(f"Comment '{comment_id}' does not exist on {_issue_identifier(issue)}")
    # The MCP only edits what it wrote: people's comments stay theirs.
    if comment.actor_id != _mcp_actor().id:
        raise MCPToolError("Only comments written through the MCP can be changed or deleted here")
    return comment


@register_tool(
    name="update_work_item_comment",
    description="Edit a comment previously written through the MCP.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "comment_id": {"type": "string"},
            "comment_html": {"type": "string"},
        },
        ["workspace_slug", "work_item", "comment_id", "comment_html"],
    ),
    category="work_items",
)
def update_work_item_comment(workspace_slug, work_item, comment_id, comment_html):
    if not comment_html:
        raise MCPToolError("'comment_html' is required")
    issue = _get_issue(workspace_slug, work_item)
    comment = _own_comment(issue, comment_id)
    before = {"id": str(comment.id), "comment_html": comment.comment_html}
    comment.comment_html = comment_html
    comment.edited_at = timezone.now()
    comment.save(update_fields=["comment_html", "edited_at", "updated_at"])
    _record_activity("comment.activity.updated", issue, _mcp_actor(), {"comment_html": comment_html}, before)
    return _comment_payload(comment)


@register_tool(
    name="delete_work_item_comment",
    description="Delete a comment previously written through the MCP.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "comment_id": {"type": "string"}},
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
    description="History of a work item: who changed what and when (newest first).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY, "limit": {"type": "integer", "default": 50}},
        ["workspace_slug", "work_item"],
    ),
    category="work_items",
)
def list_work_item_activity(workspace_slug, work_item, limit=50):
    issue = _get_issue(workspace_slug, work_item)
    limit = max(1, min(int(limit or 50), 200))
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
    description="A cycle with its progress (work items per state group) and its work items.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "cycle_id": {"type": "string"}},
        ["workspace_slug", "project", "cycle_id"],
    ),
    category="cycles",
)
def retrieve_cycle(workspace_slug, project, cycle_id):
    cycle = _get_cycle(_get_project(workspace_slug, project), cycle_id)
    issues = (
        Issue.issue_objects.filter(issue_cycle__cycle=cycle, issue_cycle__deleted_at__isnull=True)
        .select_related("project", "state")
        .prefetch_related("assignees", "labels")
        .order_by("sequence_id")
    )
    return {**_cycle_with_progress(cycle), "work_items": [_serialize_issue(issue) for issue in issues]}


@register_tool(
    name="update_cycle",
    description="Change a cycle's name, description or dates.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "cycle_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
        },
        ["workspace_slug", "project", "cycle_id"],
    ),
    category="cycles",
)
def update_cycle(workspace_slug, project, cycle_id, name=None, description=None, start_date=None, end_date=None):
    cycle = _get_cycle(_get_project(workspace_slug, project), cycle_id)
    if name is not None:
        if not name.strip():
            raise MCPToolError("'name' cannot be empty")
        cycle.name = name.strip()
    if description is not None:
        cycle.description = description
    if start_date is not None:
        cycle.start_date = _parse_date(start_date, "start_date")
    if end_date is not None:
        cycle.end_date = _parse_date(end_date, "end_date")
    if cycle.start_date and cycle.end_date and _as_date(cycle.end_date) < _as_date(cycle.start_date):
        raise MCPToolError("'end_date' must be after 'start_date'")
    cycle.save()
    cycle.refresh_from_db()
    return _cycle_with_progress(cycle)


@register_tool(
    name="delete_cycle",
    description="Delete a cycle. Its work items stay on the board, just without a cycle.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "cycle_id": {"type": "string"}},
        ["workspace_slug", "project", "cycle_id"],
    ),
    category="cycles",
)
def delete_cycle(workspace_slug, project, cycle_id):
    cycle = _get_cycle(_get_project(workspace_slug, project), cycle_id)
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
        "Put work items in a cycle. A work item belongs to one cycle at a time: items already in another cycle "
        "are moved. Completed cycles do not accept new items."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "cycle_id": {"type": "string"},
            "work_items": {"type": "array", "items": {"type": "string"}},
        },
        ["workspace_slug", "project", "cycle_id", "work_items"],
    ),
    category="cycles",
)
def add_work_items_to_cycle(workspace_slug, project, cycle_id, work_items):
    project_instance = _get_project(workspace_slug, project)
    cycle = _get_cycle(project_instance, cycle_id)
    if cycle.end_date and _as_date(cycle.end_date) < timezone.localdate():
        raise MCPToolError("This cycle is completed and cannot receive work items")
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
    description="Take a work item out of a cycle.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "cycle_id": {"type": "string"}, **_WORK_ITEM_PROPERTY},
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
        raise MCPToolError(f"{_issue_identifier(issue)} is not in cycle '{cycle.name}'")
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
    description="A module with its work items.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "module_id": {"type": "string"}},
        ["workspace_slug", "project", "module_id"],
    ),
    category="modules",
)
def retrieve_module(workspace_slug, project, module_id):
    module = _get_module(_get_project(workspace_slug, project), module_id)
    issues = (
        Issue.issue_objects.filter(issue_module__module=module, issue_module__deleted_at__isnull=True)
        .select_related("project", "state")
        .prefetch_related("assignees", "labels")
        .order_by("sequence_id")
    )
    return {**_serialize_module(module), "work_items": [_serialize_issue(issue) for issue in issues]}


@register_tool(
    name="update_module",
    description="Change a module's name, description, status or dates.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "module_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string", "enum": list(MODULE_STATUS_CHOICES)},
            "start_date": {"type": "string"},
            "target_date": {"type": "string"},
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
        raise MCPToolError(f"status must be one of {', '.join(MODULE_STATUS_CHOICES)}")
    if name is not None:
        if not name.strip():
            raise MCPToolError("'name' cannot be empty")
        module.name = name.strip()
    if description is not None:
        module.description = description
    if status is not None:
        module.status = status
    if start_date is not None:
        module.start_date = _parse_date(start_date, "start_date")
    if target_date is not None:
        module.target_date = _parse_date(target_date, "target_date")
    if module.start_date and module.target_date and module.target_date < module.start_date:
        raise MCPToolError("'target_date' must be after 'start_date'")
    try:
        module.save()
    except IntegrityError:
        raise MCPToolError(f"A module named '{module.name}' already exists in this project")
    return _serialize_module(module)


@register_tool(
    name="delete_module",
    description="Delete a module. Its work items stay on the board.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "module_id": {"type": "string"}},
        ["workspace_slug", "project", "module_id"],
    ),
    category="modules",
)
def delete_module(workspace_slug, project, module_id):
    module = _get_module(_get_project(workspace_slug, project), module_id)
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
    description="Add work items to a module (a work item can be in several modules).",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "module_id": {"type": "string"},
            "work_items": {"type": "array", "items": {"type": "string"}},
        },
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
    description="Take a work item out of a module.",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "module_id": {"type": "string"}, **_WORK_ITEM_PROPERTY},
        ["workspace_slug", "project", "module_id", "work_item"],
    ),
    category="modules",
)
def remove_work_item_from_module(workspace_slug, project, module_id, work_item):
    module = _get_module(_get_project(workspace_slug, project), module_id)
    issue = _get_issue(workspace_slug, work_item)
    link = ModuleIssue.objects.filter(module=module, issue=issue).first()
    if link is None:
        raise MCPToolError(f"{_issue_identifier(issue)} is not in module '{module.name}'")
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
    description="Add a workflow state (board column) to a project.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": {"type": "string"},
            "group": {"type": "string", "enum": list(STATE_GROUPS)},
            "color": {"type": "string", "description": "Hex color, e.g. '#3B82F6'"},
            "description": {"type": "string"},
        },
        ["workspace_slug", "project", "name", "group"],
    ),
    category="states",
)
def create_state(workspace_slug, project, name, group, color="#60646C", description=""):
    if group not in STATE_GROUPS:
        raise MCPToolError(f"group must be one of {', '.join(STATE_GROUPS)}")
    if not (name or "").strip():
        raise MCPToolError("'name' is required")
    project_instance = _get_project(workspace_slug, project)
    if State.objects.filter(project=project_instance, name__iexact=name.strip()).exists():
        raise MCPToolError(f"A state named '{name}' already exists in this project")
    last = State.objects.filter(project=project_instance).order_by("-sequence").first()
    state = State.objects.create(
        name=name.strip(),
        group=group,
        color=color or "#60646C",
        description=description or "",
        project=project_instance,
        sequence=(last.sequence + 15000) if last else 15000,
    )
    return _serialize_state(state)


@register_tool(
    name="update_state",
    description="Rename, recolor, regroup or reorder a state, or make it the default state for new work items.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "state_id": {"type": "string"},
            "name": {"type": "string"},
            "group": {"type": "string", "enum": list(STATE_GROUPS)},
            "color": {"type": "string"},
            "sequence": {"type": "number", "description": "Order on the board (lower comes first)"},
            "default": {"type": "boolean", "description": "true to make it the default state"},
        },
        ["workspace_slug", "project", "state_id"],
    ),
    category="states",
)
def update_state(workspace_slug, project, state_id, name=None, group=None, color=None, sequence=None, default=None):
    project_instance = _get_project(workspace_slug, project)
    state = _get_state(project_instance, state_id)
    if group is not None and group not in STATE_GROUPS:
        raise MCPToolError(f"group must be one of {', '.join(STATE_GROUPS)}")
    if name is not None:
        if not name.strip():
            raise MCPToolError("'name' cannot be empty")
        if State.objects.filter(project=project_instance, name__iexact=name.strip()).exclude(pk=state.pk).exists():
            raise MCPToolError(f"A state named '{name}' already exists in this project")
        state.name = name.strip()
    if group is not None:
        state.group = group
    if color is not None:
        state.color = color
    if sequence is not None:
        state.sequence = float(sequence)
    with transaction.atomic():
        if default is True:
            State.objects.filter(project=project_instance, default=True).exclude(pk=state.pk).update(default=False)
            state.default = True
            project_instance.default_state = state
            project_instance.save(update_fields=["default_state", "updated_at"])
        elif default is False and state.default:
            raise MCPToolError("Pick another state as default instead of unsetting this one")
        state.save()
    return _serialize_state(state)


@register_tool(
    name="delete_state",
    description="Delete a state. Refused for the default state or while work items still use it (move them first).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "state_id": {"type": "string"}},
        ["workspace_slug", "project", "state_id"],
    ),
    category="states",
)
def delete_state(workspace_slug, project, state_id):
    state = _get_state(_get_project(workspace_slug, project), state_id)
    if state.default:
        raise MCPToolError("The default state cannot be deleted; make another state the default first")
    in_use = Issue.objects.filter(state=state).count()
    if in_use:
        raise MCPToolError(f"{in_use} work item(s) still use this state; move them to another state first")
    name = state.name
    state.delete()
    return {"deleted": name}


@register_tool(
    name="update_label",
    description="Rename, recolor or describe a label.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "label_id": {"type": "string"},
            "name": {"type": "string"},
            "color": {"type": "string"},
            "description": {"type": "string"},
        },
        ["workspace_slug", "project", "label_id"],
    ),
    category="labels",
)
def update_label(workspace_slug, project, label_id, name=None, color=None, description=None):
    project_instance = _get_project(workspace_slug, project)
    label = _get_label(project_instance, label_id)
    if name is not None:
        if not name.strip():
            raise MCPToolError("'name' cannot be empty")
        if Label.objects.filter(project=project_instance, name=name.strip()).exclude(pk=label.pk).exists():
            raise MCPToolError(f"A label named '{name}' already exists in this project")
        label.name = name.strip()
    if color is not None:
        label.color = color
    if description is not None:
        label.description = description
    label.save()
    return _serialize_label(label)


@register_tool(
    name="delete_label",
    description="Delete a label (it is removed from every work item that had it).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "label_id": {"type": "string"}},
        ["workspace_slug", "project", "label_id"],
    ),
    category="labels",
)
def delete_label(workspace_slug, project, label_id):
    label = _get_label(_get_project(workspace_slug, project), label_id)
    name = label.name
    label.delete()
    return {"deleted": name}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@register_tool(
    name="retrieve_page",
    description="A project page with its content (HTML).",
    input_schema=_schema(
        {**_WORKSPACE_SLUG_PROPERTY, **_PROJECT_PROPERTY, "page_id": {"type": "string"}},
        ["workspace_slug", "project", "page_id"],
    ),
    category="pages",
)
def retrieve_page(workspace_slug, project, page_id):
    project_instance = _get_project(workspace_slug, project)
    page = Page.objects.filter(projects__id=project_instance.id, pk=page_id).first() if _is_uuid(page_id) else None
    if page is None:
        raise MCPToolError(f"Page '{page_id}' does not exist in project '{project_instance.identifier}'")
    return {**_serialize_page(page), "description_html": page.description_html}


@register_tool(
    name="create_page",
    description="Create a page in a project, with optional HTML content.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": {"type": "string"},
            "description_html": {"type": "string"},
            "access": {"type": "string", "enum": ["public", "private"], "description": "Default public"},
        },
        ["workspace_slug", "project", "name"],
    ),
    category="pages",
)
def create_page(workspace_slug, project, name, description_html="", access="public"):
    if not (name or "").strip():
        raise MCPToolError("'name' is required")
    project_instance = _get_project(workspace_slug, project)
    actor = _mcp_actor()
    with transaction.atomic():
        page = Page(
            name=name.strip(),
            description_html=description_html or "<p></p>",
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
        "Rename a page or replace its content. Replacing the content discards the current document, so do not "
        "use it while someone is editing the page. Locked pages are refused."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "page_id": {"type": "string"},
            "name": {"type": "string"},
            "description_html": {"type": "string"},
        },
        ["workspace_slug", "project", "page_id"],
    ),
    category="pages",
)
def update_page(workspace_slug, project, page_id, name=None, description_html=None):
    project_instance = _get_project(workspace_slug, project)
    page = Page.objects.filter(projects__id=project_instance.id, pk=page_id).first() if _is_uuid(page_id) else None
    if page is None:
        raise MCPToolError(f"Page '{page_id}' does not exist in project '{project_instance.identifier}'")
    if page.is_locked:
        raise MCPToolError("This page is locked")
    if page.archived_at is not None:
        raise MCPToolError("This page is archived")
    fields = ["updated_at"]
    if name is not None:
        page.name = name.strip()
        fields.append("name")
    if description_html is not None:
        page.description_html = description_html or "<p></p>"
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
    description="Change a project's name, description or emoji. The identifier (used in work item keys) is kept.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": {"type": "string"},
            "description": {"type": "string"},
            "emoji": {"type": "string", "description": "Emoji code point, e.g. '128640'"},
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
        name = name.strip()
        if not name:
            raise MCPToolError("'name' cannot be empty")
        if (
            Project.objects.filter(workspace_id=project_instance.workspace_id, name__iexact=name)
            .exclude(pk=project_instance.pk)
            .exists()
        ):
            raise MCPToolError(f"A project named '{name}' already exists")
        project_instance.name = name
    if description is not None:
        project_instance.description = description
    if emoji is not None:
        project_instance.emoji = emoji or None
    project_instance.save()
    return _serialize_project(project_instance)


# ---------------------------------------------------------------------------
# Project members
# ---------------------------------------------------------------------------


@register_tool(
    name="add_project_member",
    description=(
        "Add a workspace member to a project, or change their role there (admin, member or guest). "
        "The role cannot be higher than the person's role in the workspace."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "member": {"type": "string", "description": "User UUID or e-mail"},
            "role": {"type": "string", "enum": list(ROLE_CHOICES)},
        },
        ["workspace_slug", "project", "member", "role"],
    ),
    category="members",
)
def add_project_member(workspace_slug, project, member, role):
    if role not in ROLE_CHOICES:
        raise MCPToolError(f"role must be one of {', '.join(ROLE_CHOICES)}")
    project_instance = _get_project(workspace_slug, project)
    workspace_member = _user_in_workspace(project_instance.workspace, member)
    role_value = ROLE_CHOICES[role]
    if role_value > workspace_member.role:
        raise MCPToolError("The project role cannot be higher than the person's workspace role")
    project_member = ProjectMember.objects.filter(project=project_instance, member=workspace_member.member).first()
    if project_member is None:
        project_member = ProjectMember.objects.create(
            project=project_instance, member=workspace_member.member, role=role_value, is_active=True
        )
    else:
        project_member.role = role_value
        project_member.is_active = True
        project_member.save(update_fields=["role", "is_active", "updated_at"])
    return {
        **_serialize_user(workspace_member.member),
        "role": project_member.role,
        "project": project_instance.identifier,
    }


@register_tool(
    name="remove_project_member",
    description="Remove someone from a project (their work items and history stay). The last admin cannot be removed.",
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "member": {"type": "string", "description": "User UUID or e-mail"},
        },
        ["workspace_slug", "project", "member"],
    ),
    category="members",
)
def remove_project_member(workspace_slug, project, member):
    project_instance = _get_project(workspace_slug, project)
    workspace_member = _user_in_workspace(project_instance.workspace, member)
    project_member = ProjectMember.objects.filter(
        project=project_instance, member=workspace_member.member, is_active=True
    ).first()
    if project_member is None:
        raise MCPToolError(f"'{member}' is not a member of project '{project_instance.identifier}'")
    if project_member.role == ROLE_CHOICES["admin"]:
        admins = ProjectMember.objects.filter(
            project=project_instance, role=ROLE_CHOICES["admin"], is_active=True
        ).count()
        if admins <= 1:
            raise MCPToolError("This is the project's last admin")
    project_member.is_active = False
    project_member.save(update_fields=["is_active", "updated_at"])
    return {"removed": workspace_member.member.email, "project": project_instance.identifier}


# ---------------------------------------------------------------------------
# Intake (triage)
# ---------------------------------------------------------------------------


@register_tool(
    name="list_intake_items",
    description=(
        "Requests waiting in a project's intake (Entrada), from the public form or created by the team. "
        "status: pending (default), snoozed, accepted, declined, duplicate or all."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "status": {"type": "string", "enum": ["pending", "snoozed", "accepted", "declined", "duplicate", "all"]},
            "limit": {"type": "integer", "default": 50},
        },
        ["workspace_slug", "project"],
    ),
    category="intake",
)
def list_intake_items(workspace_slug, project, status="pending", limit=50):
    project_instance = _get_project(workspace_slug, project)
    limit = max(1, min(int(limit or 50), 200))
    queryset = IntakeIssue.objects.filter(project=project_instance, issue__deleted_at__isnull=True).select_related(
        "issue", "issue__project"
    )
    if status and status != "all":
        codes = {label: code for code, label in INTAKE_STATUS_LABELS.items()}
        if status not in codes:
            raise MCPToolError("status must be pending, snoozed, accepted, declined, duplicate or all")
        queryset = queryset.filter(status=codes[status])
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
                "snoozed_till": item.snoozed_till.isoformat() if item.snoozed_till else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in queryset.order_by("-created_at")[:limit]
        ]
    }


@register_tool(
    name="triage_intake_item",
    description=(
        "Decide a request in the intake: accept (it moves to the board), decline, snooze until a date, or mark "
        "it as a duplicate of another work item."
    ),
    input_schema=_schema(
        {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "action": {"type": "string", "enum": list(INTAKE_ACTIONS)},
            "snoozed_till": {"type": "string", "description": "For snooze: ISO date-time or date"},
            "duplicate_of": {"type": "string", "description": "For duplicate: identifier or UUID of the original"},
        },
        ["workspace_slug", "work_item", "action"],
    ),
    category="intake",
)
def triage_intake_item(workspace_slug, work_item, action, snoozed_till=None, duplicate_of=None):
    from django.core.serializers.json import DjangoJSONEncoder

    from plane.app.serializers import IntakeIssueSerializer

    if action not in INTAKE_ACTIONS:
        raise MCPToolError(f"action must be one of {', '.join(INTAKE_ACTIONS)}")
    issue = _get_issue(workspace_slug, work_item)
    intake_issue = IntakeIssue.objects.filter(issue=issue).first()
    if intake_issue is None:
        raise MCPToolError(f"{_issue_identifier(issue)} did not come through the intake")
    data = {"status": INTAKE_ACTIONS[action]}
    if action == "snooze":
        if not snoozed_till:
            raise MCPToolError("'snoozed_till' is required to snooze")
        data["snoozed_till"] = snoozed_till if "T" in snoozed_till else f"{snoozed_till}T09:00:00-03:00"
    if action == "duplicate":
        if not duplicate_of:
            raise MCPToolError("'duplicate_of' is required to mark as duplicate")
        original = _get_issue(workspace_slug, duplicate_of)
        if original.id == issue.id:
            raise MCPToolError("A request cannot duplicate itself")
        data["duplicate_to"] = str(original.id)
    before = json.dumps(IntakeIssueSerializer(intake_issue).data, cls=DjangoJSONEncoder)
    serializer = IntakeIssueSerializer(intake_issue, data=data, partial=True)
    if not serializer.is_valid():
        raise MCPToolError(f"Invalid triage: {serializer.errors}")
    serializer.save()
    _record_activity("intake.activity.created", issue, _mcp_actor(), data, json.loads(before))
    intake_issue.refresh_from_db()
    issue.refresh_from_db()
    return {
        "work_item": _issue_identifier(issue),
        "status": INTAKE_STATUS_LABELS.get(intake_issue.status, intake_issue.status),
        "state_id": str(issue.state_id) if issue.state_id else None,
    }
