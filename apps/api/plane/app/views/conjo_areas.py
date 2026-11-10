# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: permissions by area of the workspace (MAN-467).

- ``me/``: the areas the current user enters, for the sidebar, the routes and the work item widgets.
- configuration (workspace admins only): roles per area and per-person exceptions.
"""

# Django imports
from django.db import IntegrityError, transaction

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Workspace, WorkspaceAreaAccess, WorkspaceAreaMemberOverride, WorkspaceMember
from plane.utils import conjo_areas as areas
from plane.utils.uuid import is_valid_uuid


def _error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"error": message}, status=code)


def _member(user):
    return {
        "id": str(user.id),
        "display_name": user.display_name or user.first_name or user.email,
        "email": user.email,
        "avatar_url": getattr(user, "avatar_url", "") or "",
    }


def _configuration(workspace):
    saved = {row.area for row in WorkspaceAreaAccess.objects.filter(workspace_id=workspace.id, area__in=areas.AREAS)}
    roles = areas.roles_for(workspace.id)
    members = {
        str(m.member_id): m.role
        for m in WorkspaceMember.objects.filter(workspace_id=workspace.id, is_active=True).only("member_id", "role")
    }
    overrides = (
        WorkspaceAreaMemberOverride.objects.filter(workspace_id=workspace.id, area__in=areas.AREAS)
        .select_related("member")
        .order_by("area", "created_at")
    )
    return {
        "areas": [
            {
                "key": area,
                "label": areas.AREA_LABELS[area],
                "allowed_roles": roles[area],
                "default_roles": list(areas.DEFAULT_ROLES[area]),
                "is_default": area not in saved,
            }
            for area in areas.AREAS
        ],
        # Exceptions of people who left the workspace stay saved but have no effect; they are not listed.
        "overrides": [
            {
                "id": str(o.id),
                "area": o.area,
                "allow": o.allow,
                "member": _member(o.member),
                "role": members[str(o.member_id)],
            }
            for o in overrides
            if str(o.member_id) in members
        ],
    }


class WorkspaceMyAreasEndpoint(BaseAPIView):
    """Areas the current user enters in the workspace."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return Response({"areas": areas.areas_for(request.user, slug)})


class WorkspaceAreaAccessEndpoint(BaseAPIView):
    """Roles that enter each area. Admins always enter; only admins read or change this."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(_configuration(workspace))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        payload = request.data.get("areas")
        if not isinstance(payload, dict) or not payload:
            return _error("Informe as áreas e os papéis que acessam cada uma.")
        changes = {}
        for area, roles in payload.items():
            if area not in areas.AREAS:
                return _error("Área inválida.")
            if not isinstance(roles, list):
                return _error("Informe os papéis como uma lista (15 = Membro, 5 = Convidado).")
            if any(areas.clean_roles([role]) == [] for role in roles):
                return _error("Só os papéis Membro (15) e Convidado (5) podem ser configurados.")
            changes[area] = areas.clean_roles(roles)
        with transaction.atomic():
            for area, roles in changes.items():
                row = (
                    WorkspaceAreaAccess.objects.select_for_update().filter(workspace_id=workspace.id, area=area).first()
                )
                if row is None:
                    WorkspaceAreaAccess.objects.create(workspace=workspace, area=area, allowed_roles=roles)
                elif row.allowed_roles != roles:
                    row.allowed_roles = roles
                    row.save(update_fields=["allowed_roles", "updated_at", "updated_by"])
        return Response(_configuration(workspace))


class WorkspaceAreaOverridesEndpoint(BaseAPIView):
    """Lets one person in, or keeps them out, of an area above their role. Never applies to admins."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        area = request.data.get("area")
        member_id = str(request.data.get("member_id") or "")
        allow = request.data.get("allow")
        if area not in areas.AREAS:
            return _error("Área inválida.")
        if not isinstance(allow, bool):
            return _error("Escolha liberar ou bloquear.")
        membership = (
            WorkspaceMember.objects.filter(workspace_id=workspace.id, member_id=member_id, is_active=True).first()
            if is_valid_uuid(member_id)
            else None
        )
        if membership is None:
            return _error("Membro não encontrado neste workspace.", status.HTTP_404_NOT_FOUND)
        if membership.role == ROLE.ADMIN.value:
            return _error("Administradores sempre acessam todas as áreas; não há exceção para eles.")
        try:
            with transaction.atomic():
                row = (
                    WorkspaceAreaMemberOverride.objects.select_for_update()
                    .filter(workspace_id=workspace.id, area=area, member_id=membership.member_id)
                    .first()
                )
                if row is None:
                    WorkspaceAreaMemberOverride.objects.create(
                        workspace=workspace, area=area, member_id=membership.member_id, allow=allow
                    )
                elif row.allow != allow:
                    row.allow = allow
                    row.save(update_fields=["allow", "updated_at", "updated_by"])
        except IntegrityError:
            # Two admins saving the same exception at once: the other one won, show what is saved.
            pass
        return Response(_configuration(workspace))


class WorkspaceAreaOverrideDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, override_id):
        workspace = Workspace.objects.get(slug=slug)
        removed = WorkspaceAreaMemberOverride.objects.filter(workspace_id=workspace.id, pk=override_id).delete()
        if not removed:
            return _error("Exceção não encontrada.", status.HTTP_404_NOT_FOUND)
        return Response(_configuration(workspace))
