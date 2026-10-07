# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Realtime: the live server asks, with the browser's own session, whether it may join a project's room."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ProjectMember


class ProjectRealtimeAccessEndpoint(BaseAPIView):
    """200 for active members of the project (guests included), 403 otherwise.

    ``restricted`` is true for guests who only see the work items they created, so the
    live server only relays events about those items to them.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project = Project.objects.filter(workspace__slug=slug, pk=project_id, archived_at__isnull=True).first()
        if project is None:
            return Response({"error": "Projeto não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        is_guest = ProjectMember.objects.filter(
            project_id=project_id, member=request.user, role=ROLE.GUEST.value, is_active=True
        ).exists()
        return Response(
            {
                "user_id": str(request.user.id),
                "project_id": str(project.id),
                "restricted": bool(is_guest and not project.guest_view_all_features),
            }
        )
