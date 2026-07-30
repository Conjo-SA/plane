# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, IntakeIssue, IntakePortal, State, StateGroup
from plane.db.models.intake import SourceType
from plane.utils.content_validator import validate_html_content

from .base import BaseAPIView

VALID_PRIORITIES = ["urgent", "high", "medium", "low", "none"]
MAX_NAME_LENGTH = 255
MAX_REQUESTER_NAME_LENGTH = 120


def get_enabled_portal(anchor):
    """Return the enabled portal for the given anchor, or None."""
    return (
        IntakePortal.objects.filter(anchor=anchor, is_enabled=True)
        .select_related("project", "workspace", "intake")
        .first()
    )


class IntakePortalMetaEndpoint(BaseAPIView):
    """Public metadata for the request form. Exposes only presentation data."""

    permission_classes = [AllowAny]

    def get(self, request, anchor):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "anchor": portal.anchor,
                "title": portal.title or portal.project.name,
                "description": portal.description,
                "success_message": portal.success_message,
                "is_attachment_enabled": portal.is_attachment_enabled,
                "project_name": portal.project.name,
                "workspace_name": portal.workspace.name,
                "logo_props": portal.project.logo_props,
            },
            status=status.HTTP_200_OK,
        )


class IntakePortalWorkItemEndpoint(BaseAPIView):
    """Anonymous work item submission into a project's intake."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "intake_portal"

    def post(self, request, anchor):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "Name is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(name) > MAX_NAME_LENGTH:
            return Response(
                {"error": f"Name cannot exceed {MAX_NAME_LENGTH} characters"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        priority = request.data.get("priority") or "none"
        if priority not in VALID_PRIORITIES:
            return Response({"error": "Invalid priority"}, status=status.HTTP_400_BAD_REQUEST)

        requester_email = (request.data.get("requester_email") or "").strip()
        if not requester_email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_email(requester_email)
        except ValidationError:
            return Response({"error": "Enter a valid email address"}, status=status.HTTP_400_BAD_REQUEST)

        requester_name = (request.data.get("requester_name") or "").strip()[:MAX_REQUESTER_NAME_LENGTH]

        # Sanitize description_html before saving to prevent stored XSS
        _, _, sanitized_description_html = validate_html_content(request.data.get("description_html", "<p></p>"))
        safe_description_html = sanitized_description_html if sanitized_description_html is not None else "<p></p>"

        # Intake work items always land on the triage state
        triage_state = State.triage_objects.filter(
            project_id=portal.project_id, workspace_id=portal.workspace_id
        ).first()
        if not triage_state:
            triage_state = State.objects.create(
                name="Triage",
                group=StateGroup.TRIAGE.value,
                project_id=portal.project_id,
                workspace_id=portal.workspace_id,
                color="#4E5355",
                sequence=65000,
                default=False,
            )

        issue = Issue.objects.create(
            name=name,
            description_html=safe_description_html,
            priority=priority,
            project_id=portal.project_id,
            state_id=triage_state.id,
        )

        IntakeIssue.objects.create(
            intake_id=portal.intake_id,
            project_id=portal.project_id,
            issue=issue,
            source=SourceType.PORTAL,
            source_email=requester_email,
            extra={"requester_name": requester_name, "portal_anchor": portal.anchor},
        )

        issue_activity.delay(
            type="issue.activity.created",
            requested_data=json.dumps({"name": name, "priority": priority}, cls=DjangoJSONEncoder),
            actor_id=None,
            issue_id=str(issue.id),
            project_id=str(portal.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
        )

        return Response(
            {
                "id": str(issue.id),
                "sequence_id": issue.sequence_id,
                "success_message": portal.success_message,
            },
            status=status.HTTP_201_CREATED,
        )
