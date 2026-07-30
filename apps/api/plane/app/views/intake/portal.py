# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IntakePortalSerializer
from plane.app.views.base import BaseAPIView
from plane.db.models import Intake, IntakePortal
from plane.db.models.intake import get_intake_portal_anchor

EDITABLE_FIELDS = ["is_enabled", "title", "description", "success_message", "is_attachment_enabled"]


class IntakePortalEndpoint(BaseAPIView):
    """Manage the public request form of a project."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        portal = IntakePortal.objects.filter(workspace__slug=slug, project_id=project_id).first()
        if portal is None:
            return Response({}, status=status.HTTP_200_OK)
        return Response(IntakePortalSerializer(portal).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        portal = IntakePortal.objects.filter(workspace__slug=slug, project_id=project_id).first()
        if portal is not None:
            return Response(IntakePortalSerializer(portal).data, status=status.HTTP_200_OK)

        intake = Intake.objects.filter(workspace__slug=slug, project_id=project_id, is_default=True).first()
        if intake is None:
            return Response(
                {"error": "Enable Intake for this project before creating a request form."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        portal = IntakePortal.objects.create(
            intake=intake,
            project_id=project_id,
            workspace_id=intake.workspace_id,
            is_enabled=bool(request.data.get("is_enabled", False)),
            title=request.data.get("title", ""),
            description=request.data.get("description", ""),
            success_message=request.data.get("success_message", ""),
        )
        return Response(IntakePortalSerializer(portal).data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id):
        portal = IntakePortal.objects.filter(workspace__slug=slug, project_id=project_id).first()
        if portal is None:
            return Response({"error": "Request form not found"}, status=status.HTTP_404_NOT_FOUND)

        if request.data.get("regenerate_anchor"):
            portal.anchor = get_intake_portal_anchor()
            portal.save(update_fields=["anchor"])

        payload = {field: request.data[field] for field in EDITABLE_FIELDS if field in request.data}
        serializer = IntakePortalSerializer(portal, data=payload, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id):
        portal = IntakePortal.objects.filter(workspace__slug=slug, project_id=project_id).first()
        if portal is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        portal.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
