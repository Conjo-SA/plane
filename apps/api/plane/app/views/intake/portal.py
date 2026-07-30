# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import re

# Django imports
from django.db.models import Q

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

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,58}[a-z0-9]$")


def validate_portal_slug(raw_slug, portal):
    """Normalize and validate a custom slug.

    Returns (slug, error). An empty value clears the slug. The slug must not
    collide with another portal's slug or with any anchor, since both are
    resolved from the same URL segment.
    """
    slug = (raw_slug or "").strip().lower()
    if not slug:
        return None, None

    if not SLUG_PATTERN.match(slug):
        return None, (
            "Use 3 to 60 characters with lowercase letters, numbers, hyphens or underscores, "
            "starting and ending with a letter or number."
        )

    conflict = (
        IntakePortal.objects.filter(Q(slug__iexact=slug) | Q(anchor__iexact=slug)).exclude(pk=portal.pk).exists()
    )
    if conflict:
        return None, "This link is already taken. Choose another one."

    return slug, None


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

        if "slug" in request.data:
            slug_value, slug_error = validate_portal_slug(request.data.get("slug"), portal)
            if slug_error:
                return Response({"error": slug_error}, status=status.HTTP_400_BAD_REQUEST)
            portal.slug = slug_value
            portal.save(update_fields=["slug"])

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
