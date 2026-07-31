# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import re

# Django imports
from django.db.models import Q
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IntakePortalSerializer
from plane.app.views.base import BaseAPIView
from plane.bgtasks.intake_portal_task import send_portal_budget_request
from plane.db.models import Intake, IntakeIssue, IntakePortal, IntakePortalBudget
from plane.db.models.intake import IntakePortalBudgetStatus, SourceType, get_intake_portal_anchor
from plane.utils.intake_portal import parse_estimated_hours, serialize_portal_budget

EDITABLE_FIELDS = ["is_enabled", "title", "description", "success_message", "is_attachment_enabled"]

MAX_BUDGET_NOTE_LENGTH = 2000

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


class IntakePortalBudgetEndpoint(BaseAPIView):
    """Hourly estimate the team sends to a portal requester for approval."""

    def get_portal_ticket(self, slug, project_id, issue_id):
        """Only tickets that came from the portal have a requester who can approve."""
        return (
            IntakeIssue.objects.filter(
                issue_id=issue_id,
                project_id=project_id,
                workspace__slug=slug,
                source=SourceType.PORTAL,
                source_email__isnull=False,
            )
            .select_related("issue")
            .first()
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, issue_id):
        intake_issue = self.get_portal_ticket(slug, project_id, issue_id)
        if intake_issue is None:
            return Response({"is_portal_ticket": False, "budget": None}, status=status.HTTP_200_OK)

        budget = IntakePortalBudget.objects.filter(issue_id=issue_id).first()
        return Response(
            {"is_portal_ticket": True, "budget": serialize_portal_budget(budget)},
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        intake_issue = self.get_portal_ticket(slug, project_id, issue_id)
        if intake_issue is None:
            return Response(
                {"error": "Este item não veio do portal, então não há cliente para aprovar o orçamento."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        hours, hours_error = parse_estimated_hours(request.data.get("estimated_hours"))
        if hours_error:
            return Response({"error": hours_error}, status=status.HTTP_400_BAD_REQUEST)

        note = (request.data.get("note") or "").strip()[:MAX_BUDGET_NOTE_LENGTH]

        budget = IntakePortalBudget.objects.filter(issue_id=issue_id).first()
        # An approved estimate is a settled agreement, so it is never repriced.
        if budget is not None and budget.status == IntakePortalBudgetStatus.APPROVED:
            return Response(
                {"error": "Este orçamento já foi aprovado pelo cliente e não pode ser alterado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if budget is None:
            budget = IntakePortalBudget(
                issue_id=issue_id,
                project_id=project_id,
                workspace_id=intake_issue.workspace_id,
            )

        budget.estimated_hours = hours
        budget.note = note
        budget.status = IntakePortalBudgetStatus.PENDING
        budget.requested_at = timezone.now()
        budget.save()

        send_portal_budget_request.delay(str(issue_id))

        return Response(serialize_portal_budget(budget), status=status.HTTP_200_OK)
