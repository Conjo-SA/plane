# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Domain handlers for the Plane MCP server.

Every handler is registered through `@register_tool` and receives plain
JSON-compatible arguments. Handlers raise `MCPToolError` for expected
failures (missing entities, invalid payloads) — the MCP server turns them
into `isError: True` tool results.
"""

# Python imports
import datetime
from uuid import UUID

# Django imports
from django.db import IntegrityError
from django.db.models import Q

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
    Workspace,
    WorkspaceMember,
)
from plane.mcp.tools.registry import register_tool

PRIORITY_CHOICES = ("urgent", "high", "medium", "low", "none")
MODULE_STATUS_CHOICES = ("backlog", "planned", "in-progress", "paused", "completed", "cancelled")


class MCPToolError(Exception):
    """Expected tool failure surfaced to the MCP client as an error result."""


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _is_uuid(value):
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _get_workspace(slug):
    workspace = Workspace.objects.filter(slug=slug).first()
    if workspace is None:
        raise MCPToolError(f"Workspace with slug '{slug}' does not exist")
    return workspace


def _get_project(workspace_slug, project):
    """Resolve a project by UUID or by its identifier (e.g. `PLANE`)."""
    queryset = Project.objects.filter(workspace__slug=workspace_slug)
    if _is_uuid(project):
        instance = queryset.filter(pk=project).first()
    else:
        instance = queryset.filter(identifier=str(project).strip().upper()).first()
    if instance is None:
        raise MCPToolError(f"Project '{project}' does not exist in workspace '{workspace_slug}'")
    return instance


def _get_issue(workspace_slug, issue):
    """Resolve an issue by UUID or by its human identifier (e.g. `PLANE-123`)."""
    queryset = Issue.objects.filter(workspace__slug=workspace_slug).select_related("project")
    if _is_uuid(issue):
        instance = queryset.filter(pk=issue).first()
    else:
        try:
            project_identifier, sequence_id = str(issue).rsplit("-", 1)
            sequence_id = int(sequence_id)
        except (ValueError, AttributeError):
            raise MCPToolError(
                f"Work item '{issue}' is not a valid UUID or identifier like 'PLANE-123'"
            )
        instance = queryset.filter(
            project__identifier=project_identifier.strip().upper(), sequence_id=sequence_id
        ).first()
    if instance is None:
        raise MCPToolError(f"Work item '{issue}' does not exist in workspace '{workspace_slug}'")
    return instance


def _parse_date(value, field_name):
    if value in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise MCPToolError(f"'{field_name}' must be an ISO date (YYYY-MM-DD)")


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


def _serialize_issue(issue, include_description=False):
    data = {
        "id": str(issue.id),
        "identifier": _issue_identifier(issue),
        "name": issue.name,
        "priority": issue.priority,
        "sequence_id": issue.sequence_id,
        "state_id": str(issue.state_id) if issue.state_id else None,
        "project_id": str(issue.project_id),
        "workspace_id": str(issue.workspace_id),
        "start_date": issue.start_date.isoformat() if issue.start_date else None,
        "target_date": issue.target_date.isoformat() if issue.target_date else None,
        "assignee_ids": [str(assignee_id) for assignee_id in issue.assignees.values_list("id", flat=True)]
        if hasattr(issue, "assignees")
        else [],
        "label_ids": [str(label_id) for label_id in issue.labels.values_list("id", flat=True)]
        if hasattr(issue, "labels")
        else [],
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
        "access": page.access,
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
        "description": "Slug of the workspace, e.g. 'my-company'",
    }
}

_PROJECT_PROPERTY = {
    "project": {
        "type": "string",
        "description": "Project UUID or project identifier, e.g. 'PLANE'",
    }
}

_WORK_ITEM_PROPERTY = {
    "work_item": {
        "type": "string",
        "description": "Work item UUID or human identifier, e.g. 'PLANE-123'",
    }
}


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_workspaces",
    description="List all workspaces in this Plane instance.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    category="workspaces",
)
def list_workspaces():
    workspaces = Workspace.objects.all().order_by("name")
    return {"workspaces": [_serialize_workspace(workspace) for workspace in workspaces]}


@register_tool(
    name="retrieve_workspace",
    description="Retrieve details of a single workspace by its slug.",
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
    description="List all projects in a workspace.",
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
    description="Retrieve details of a single project by UUID or identifier.",
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
        "Create a new project in a workspace. Seeds the default workflow states "
        "(Backlog, Todo, In Progress, Done, Cancelled, Triage)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            "name": {"type": "string", "description": "Name of the project"},
            "identifier": {
                "type": "string",
                "description": "Short uppercase identifier used in work item ids, e.g. 'PLANE'",
                "maxLength": 12,
            },
            "description": {"type": "string", "description": "Optional plain-text description"},
        },
        "required": ["workspace_slug", "name", "identifier"],
        "additionalProperties": False,
    },
    category="projects",
)
def create_project(workspace_slug, name, identifier, description=""):
    workspace = _get_workspace(workspace_slug)
    identifier = str(identifier).strip().upper()

    if Project.objects.filter(workspace=workspace, identifier=identifier).exists():
        raise MCPToolError(f"A project with identifier '{identifier}' already exists in this workspace")

    try:
        project = Project.objects.create(
            name=name,
            identifier=identifier,
            description=description or "",
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
        raise MCPToolError(f"A project with name '{name}' or identifier '{identifier}' already exists")

    return _serialize_project(project)


# ---------------------------------------------------------------------------
# Member tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_workspace_members",
    description="List all active members of a workspace.",
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
    members = WorkspaceMember.objects.filter(
        workspace__slug=workspace_slug, is_active=True
    ).select_related("member")
    return {
        "members": [
            {**_serialize_user(member.member), "role": member.role}
            for member in members
            if member.member is not None
        ]
    }


@register_tool(
    name="list_project_members",
    description="List all active members of a project.",
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
            {**_serialize_user(member.member), "role": member.role}
            for member in members
            if member.member is not None
        ]
    }


# ---------------------------------------------------------------------------
# Work item tools
# ---------------------------------------------------------------------------


def _filtered_issues(workspace_slug, project=None, query=None, state_id=None, priority=None, assignee_id=None):
    queryset = (
        Issue.objects.filter(workspace__slug=workspace_slug, archived_at__isnull=True)
        .select_related("project")
        .prefetch_related("assignees", "labels")
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
        queryset = queryset.filter(assignees__id=assignee_id)
    return queryset.order_by("-created_at").distinct()


@register_tool(
    name="list_work_items",
    description=(
        "List work items in a workspace or project. Optionally filter by state, "
        "priority (urgent|high|medium|low|none) or assignee. Returns at most `limit` items."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "state_id": {"type": "string", "description": "Filter by state UUID"},
            "priority": {
                "type": "string",
                "enum": list(PRIORITY_CHOICES),
                "description": "Filter by priority",
            },
            "assignee_id": {"type": "string", "description": "Filter by assignee user UUID"},
            "limit": {
                "type": "integer",
                "description": "Maximum number of work items to return (default 50, max 200)",
                "default": 50,
            },
        },
        "required": ["workspace_slug"],
        "additionalProperties": False,
    },
    category="work_items",
)
def list_work_items(workspace_slug, project=None, state_id=None, priority=None, assignee_id=None, limit=50):
    _get_workspace(workspace_slug)
    if priority is not None and priority not in PRIORITY_CHOICES:
        raise MCPToolError(f"priority must be one of {', '.join(PRIORITY_CHOICES)}")
    limit = max(1, min(int(limit or 50), 200))
    issues = _filtered_issues(
        workspace_slug, project=project, state_id=state_id, priority=priority, assignee_id=assignee_id
    )[:limit]
    return {"work_items": [_serialize_issue(issue) for issue in issues]}


@register_tool(
    name="retrieve_work_item",
    description="Retrieve a single work item (including its description) by UUID or identifier like 'PLANE-123'.",
    input_schema={
        "type": "object",
        "properties": {**_WORKSPACE_SLUG_PROPERTY, **_WORK_ITEM_PROPERTY},
        "required": ["workspace_slug", "work_item"],
        "additionalProperties": False,
    },
    category="work_items",
)
def retrieve_work_item(workspace_slug, work_item):
    issue = _get_issue(workspace_slug, work_item)
    return _serialize_issue(issue, include_description=True)


@register_tool(
    name="search_work_items",
    description="Full-text search over work item names and descriptions inside a workspace or project.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "query": {"type": "string", "description": "Search text"},
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default 25, max 100)",
                "default": 25,
            },
        },
        "required": ["workspace_slug", "query"],
        "additionalProperties": False,
    },
    category="work_items",
)
def search_work_items(workspace_slug, query, project=None, limit=25):
    _get_workspace(workspace_slug)
    if not query:
        raise MCPToolError("'query' is required")
    limit = max(1, min(int(limit or 25), 100))
    issues = _filtered_issues(workspace_slug, project=project, query=query)[:limit]
    return {"work_items": [_serialize_issue(issue) for issue in issues]}


def _validate_priority(priority):
    if priority is not None and priority not in PRIORITY_CHOICES:
        raise MCPToolError(f"priority must be one of {', '.join(PRIORITY_CHOICES)}")


def _validate_state(project_instance, state_id):
    if state_id in (None, ""):
        return None
    state = State.objects.filter(project=project_instance, pk=state_id).first()
    if state is None:
        raise MCPToolError(f"State '{state_id}' does not exist in project '{project_instance.identifier}'")
    return state


def _set_issue_assignees(issue, project_instance, assignee_ids):
    if assignee_ids is None:
        return
    IssueAssignee.objects.filter(issue=issue).delete()
    valid_member_ids = ProjectMember.objects.filter(
        project=project_instance, is_active=True, member_id__in=assignee_ids
    ).values_list("member_id", flat=True)
    IssueAssignee.objects.bulk_create(
        [
            IssueAssignee(
                issue=issue,
                assignee_id=member_id,
                project=project_instance,
                workspace=issue.workspace,
            )
            for member_id in valid_member_ids
        ],
        batch_size=10,
        ignore_conflicts=True,
    )


def _set_issue_labels(issue, project_instance, label_ids):
    if label_ids is None:
        return
    IssueLabel.objects.filter(issue=issue).delete()
    valid_label_ids = Label.objects.filter(project=project_instance, id__in=label_ids).values_list("id", flat=True)
    IssueLabel.objects.bulk_create(
        [
            IssueLabel(
                issue=issue,
                label_id=label_id,
                project=project_instance,
                workspace=issue.workspace,
            )
            for label_id in valid_label_ids
        ],
        batch_size=10,
        ignore_conflicts=True,
    )


@register_tool(
    name="create_work_item",
    description=(
        "Create a work item in a project. Provide the project by UUID or identifier. "
        "Optionally set state, priority, dates, assignees and labels."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            "project": {
                "type": "string",
                "description": "Project UUID or project identifier, e.g. 'PLANE'",
            },
            "name": {"type": "string", "description": "Title of the work item"},
            "description_html": {
                "type": "string",
                "description": "Optional HTML description of the work item",
            },
            "priority": {
                "type": "string",
                "enum": list(PRIORITY_CHOICES),
                "description": "Priority of the work item",
            },
            "state_id": {"type": "string", "description": "UUID of the workflow state"},
            "start_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
            "target_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
            "assignee_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "User UUIDs of assignees (must be project members)",
            },
            "label_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Label UUIDs to attach",
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
):
    if not name:
        raise MCPToolError("'name' is required")
    _validate_priority(priority)
    project_instance = _get_project(workspace_slug, project)
    state = _validate_state(project_instance, state_id)

    issue_type = IssueType.objects.filter(
        project_issue_types__project_id=project_instance.id, is_default=True
    ).first()

    issue = Issue.objects.create(
        name=name,
        description_html=description_html or "<p></p>",
        priority=priority or "none",
        state=state or project_instance.default_state,
        project=project_instance,
        type=issue_type,
        start_date=_parse_date(start_date, "start_date"),
        target_date=_parse_date(target_date, "target_date"),
    )

    _set_issue_assignees(issue, project_instance, assignee_ids)
    _set_issue_labels(issue, project_instance, label_ids)

    return _serialize_issue(issue, include_description=True)


@register_tool(
    name="update_work_item",
    description=(
        "Update fields of an existing work item. Only the provided fields are changed. "
        "Assignees and labels, when provided, replace the current values."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "name": {"type": "string"},
            "description_html": {"type": "string"},
            "priority": {"type": "string", "enum": list(PRIORITY_CHOICES)},
            "state_id": {"type": "string", "description": "UUID of the workflow state"},
            "start_date": {"type": "string", "description": "ISO date (YYYY-MM-DD) or empty string to clear"},
            "target_date": {"type": "string", "description": "ISO date (YYYY-MM-DD) or empty string to clear"},
            "assignee_ids": {"type": "array", "items": {"type": "string"}},
            "label_ids": {"type": "array", "items": {"type": "string"}},
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
):
    issue = _get_issue(workspace_slug, work_item)
    _validate_priority(priority)

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
    if state_id is not None:
        issue.state = _validate_state(issue.project, state_id)
        update_fields.append("state")
    if start_date is not None:
        issue.start_date = _parse_date(start_date, "start_date")
        update_fields.append("start_date")
    if target_date is not None:
        issue.target_date = _parse_date(target_date, "target_date")
        update_fields.append("target_date")

    if update_fields:
        update_fields.append("updated_at")
        issue.save(update_fields=update_fields)

    _set_issue_assignees(issue, issue.project, assignee_ids)
    _set_issue_labels(issue, issue.project, label_ids)

    return _serialize_issue(issue, include_description=True)


@register_tool(
    name="add_work_item_comment",
    description="Add an HTML comment to a work item.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_WORK_ITEM_PROPERTY,
            "comment_html": {"type": "string", "description": "HTML body of the comment"},
        },
        "required": ["workspace_slug", "work_item", "comment_html"],
        "additionalProperties": False,
    },
    category="work_items",
)
def add_work_item_comment(workspace_slug, work_item, comment_html):
    if not comment_html:
        raise MCPToolError("'comment_html' is required")
    issue = _get_issue(workspace_slug, work_item)
    comment = IssueComment.objects.create(
        issue=issue,
        project=issue.project,
        comment_html=comment_html,
    )
    return {
        "id": str(comment.id),
        "work_item": _issue_identifier(issue),
        "comment_html": comment.comment_html,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


# ---------------------------------------------------------------------------
# Cycle tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_cycles",
    description="List all cycles of a project.",
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
    description="Create a cycle in a project with start and end dates.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": {"type": "string"},
            "description": {"type": "string"},
            "start_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
        },
        "required": ["workspace_slug", "project", "name", "start_date", "end_date"],
        "additionalProperties": False,
    },
    category="cycles",
)
def create_cycle(workspace_slug, project, name, start_date, end_date, description=""):
    if not name:
        raise MCPToolError("'name' is required")
    project_instance = _get_project(workspace_slug, project)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start is None or end is None:
        raise MCPToolError("'start_date' and 'end_date' are required")
    if end < start:
        raise MCPToolError("'end_date' must be after 'start_date'")

    cycle = Cycle.objects.create(
        name=name,
        description=description or "",
        project=project_instance,
        start_date=start,
        end_date=end,
    )
    return _serialize_cycle(cycle)


# ---------------------------------------------------------------------------
# Module tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_modules",
    description="List all modules of a project.",
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
    description="Create a module in a project.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": list(MODULE_STATUS_CHOICES),
                "description": "Module status (defaults to the model default when omitted)",
            },
            "start_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
            "target_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
        },
        "required": ["workspace_slug", "project", "name"],
        "additionalProperties": False,
    },
    category="modules",
)
def create_module(workspace_slug, project, name, description="", status=None, start_date=None, target_date=None):
    if not name:
        raise MCPToolError("'name' is required")
    if status is not None and status not in MODULE_STATUS_CHOICES:
        raise MCPToolError(f"status must be one of {', '.join(MODULE_STATUS_CHOICES)}")
    project_instance = _get_project(workspace_slug, project)

    module_kwargs = {
        "name": name,
        "description": description or "",
        "project": project_instance,
        "start_date": _parse_date(start_date, "start_date"),
        "target_date": _parse_date(target_date, "target_date"),
    }
    if status is not None:
        module_kwargs["status"] = status

    module = Module.objects.create(**module_kwargs)
    return _serialize_module(module)


# ---------------------------------------------------------------------------
# State tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_states",
    description="List all workflow states of a project.",
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
    description="List all labels of a project.",
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
    description="Create a label in a project.",
    input_schema={
        "type": "object",
        "properties": {
            **_WORKSPACE_SLUG_PROPERTY,
            **_PROJECT_PROPERTY,
            "name": {"type": "string"},
            "color": {
                "type": "string",
                "description": "Hex color of the label, e.g. '#F59E0B' (default '#FF6900')",
            },
            "description": {"type": "string"},
        },
        "required": ["workspace_slug", "project", "name"],
        "additionalProperties": False,
    },
    category="labels",
)
def create_label(workspace_slug, project, name, color=None, description=""):
    if not name:
        raise MCPToolError("'name' is required")
    project_instance = _get_project(workspace_slug, project)
    if Label.objects.filter(project=project_instance, name=name).exists():
        raise MCPToolError(f"A label named '{name}' already exists in this project")
    label = Label.objects.create(
        name=name,
        color=color or "#FF6900",
        description=description or "",
        project=project_instance,
    )
    return _serialize_label(label)


# ---------------------------------------------------------------------------
# Page tools
# ---------------------------------------------------------------------------


@register_tool(
    name="list_pages",
    description="List all pages linked to a project.",
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
    pages = (
        Page.objects.filter(projects__id=project_instance.id, archived_at__isnull=True)
        .order_by("-created_at")
        .distinct()
    )
    return {"pages": [_serialize_page(page) for page in pages]}
