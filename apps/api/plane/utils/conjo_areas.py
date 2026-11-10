# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: access to each area of the workspace (MAN-467).

One rule, used by every endpoint of an area and by the front (``areas_for``):

1. Only active members of the workspace enter any area.
2. The workspace admin always enters (nobody locks themselves out).
3. A per-person exception (allow or block) wins over the role.
4. Otherwise the roles saved for the area decide; without a saved configuration, ``DEFAULT_ROLES``.

The area is an extra gate on top of the role checks of each endpoint: it never grants a write the role
does not allow, and the per-project visibility filters keep applying.
"""

from plane.db.models import WorkspaceAreaAccess, WorkspaceAreaMemberOverride, WorkspaceMember
from plane.utils.uuid import is_valid_uuid

ADMIN = 20
MEMBER = 15
GUEST = 5

# Roles (besides the admin) that may be granted an area.
CONFIGURABLE_ROLES = (MEMBER, GUEST)

AREAS = ("clients", "docs", "time", "integrations", "archives")

AREA_LABELS = {
    "clients": "Clientes",
    "docs": "Documentação",
    "time": "Horas e orçamento",
    "integrations": "Integrações",
    "archives": "Arquivos",
}

# Without a saved configuration. Clients is admin-only; the others keep the access they had before MAN-467.
DEFAULT_ROLES = {
    "clients": [],
    "docs": [MEMBER, GUEST],
    "time": [MEMBER, GUEST],
    "integrations": [MEMBER],
    "archives": [MEMBER],
}

DENIED_MESSAGE = "Você não tem acesso à área {label} neste workspace. Peça a um administrador."


def denied_message(area):
    return DENIED_MESSAGE.format(label=AREA_LABELS.get(area, area))


def clean_roles(roles):
    """Keep only configurable roles, without repetition, in a stable order."""
    values = set()
    for role in roles or []:
        try:
            value = int(role)
        except (TypeError, ValueError):
            continue
        if value in CONFIGURABLE_ROLES:
            values.add(value)
    return sorted(values, reverse=True)


def _workspace_lookup(workspace):
    """Accepts a Workspace, its id or its slug."""
    workspace_id = getattr(workspace, "id", None)
    if workspace_id is not None:
        return {"workspace_id": workspace_id}
    value = str(workspace or "")
    if is_valid_uuid(value):
        return {"workspace_id": value}
    return {"workspace__slug": value}


def _membership(user, workspace):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        WorkspaceMember.objects.filter(member_id=user.id, is_active=True, **_workspace_lookup(workspace))
        .only("id", "role", "workspace_id")
        .first()
    )


def roles_for(workspace_id):
    """Allowed roles of every area for the workspace (saved configuration or default)."""
    saved = {
        row.area: clean_roles(row.allowed_roles)
        for row in WorkspaceAreaAccess.objects.filter(workspace_id=workspace_id, area__in=AREAS)
    }
    return {area: saved.get(area, list(DEFAULT_ROLES[area])) for area in AREAS}


def _decide(role, override, allowed_roles):
    if role == ADMIN:
        return True
    if override is not None:
        return bool(override)
    return role in allowed_roles


def has_area_access(user, workspace, area):
    """Whether ``user`` enters ``area`` of ``workspace`` (a Workspace, its id or its slug)."""
    if area not in AREAS:
        return False
    membership = _membership(user, workspace)
    if membership is None:
        return False
    if membership.role == ADMIN:
        return True
    override = (
        WorkspaceAreaMemberOverride.objects.filter(workspace_id=membership.workspace_id, area=area, member_id=user.id)
        .values_list("allow", flat=True)
        .first()
    )
    row = WorkspaceAreaAccess.objects.filter(workspace_id=membership.workspace_id, area=area).first()
    allowed = clean_roles(row.allowed_roles) if row else DEFAULT_ROLES[area]
    return _decide(membership.role, override, allowed)


def areas_for(user, workspace):
    """``{area: bool}`` for the current user, for the front (sidebar, routes and widgets)."""
    membership = _membership(user, workspace)
    if membership is None:
        return {area: False for area in AREAS}
    roles = roles_for(membership.workspace_id)
    overrides = dict(
        WorkspaceAreaMemberOverride.objects.filter(
            workspace_id=membership.workspace_id, member_id=user.id, area__in=AREAS
        ).values_list("area", "allow")
    )
    return {area: _decide(membership.role, overrides.get(area), roles[area]) for area in AREAS}
