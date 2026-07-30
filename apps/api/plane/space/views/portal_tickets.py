# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Prefetch

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

# Module imports
from plane.bgtasks.intake_portal_task import send_portal_verification_code
from plane.db.models import IntakeIssue, Issue, IssueComment
from plane.db.models.intake import SourceType

from .base import BaseAPIView
from .intake_portal import get_enabled_portal
from .portal_auth import (
    create_session,
    create_verification,
    is_on_cooldown,
    normalize_email,
    resolve_session,
    verify_code,
)

MAX_TICKETS = 100


class IntakePortalVerificationEndpoint(BaseAPIView):
    """Send a one-time code to the requester email."""

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

        email = normalize_email(request.data.get("email"))
        if email is None:
            return Response({"error": "Informe um e-mail válido."}, status=status.HTTP_400_BAD_REQUEST)

        if is_on_cooldown(email, portal.workspace_id):
            return Response(
                {"error": "Aguarde um minuto antes de solicitar um novo código."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = create_verification(email, portal.workspace_id, portal.project_id)
        send_portal_verification_code.delay(email, code, portal.project.name)

        return Response({"message": "Código enviado."}, status=status.HTTP_200_OK)


class IntakePortalVerificationConfirmEndpoint(BaseAPIView):
    """Validate the one-time code and issue a portal session."""

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

        email = normalize_email(request.data.get("email"))
        if email is None:
            return Response({"error": "Informe um e-mail válido."}, status=status.HTTP_400_BAD_REQUEST)

        is_valid, error = verify_code(email, portal.workspace_id, request.data.get("code"))
        if not is_valid:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        token = create_session(email, portal.workspace_id, portal.project_id)
        return Response({"token": token, "email": email}, status=status.HTTP_200_OK)


class IntakePortalTicketsEndpoint(BaseAPIView):
    """List the tickets opened by the authenticated requester."""

    permission_classes = [AllowAny]

    def get(self, request, anchor):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = resolve_session(request, portal.workspace_id)
        if session is None:
            return Response({"error": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED)

        intake_issues = (
            IntakeIssue.objects.filter(
                workspace_id=portal.workspace_id,
                source=SourceType.PORTAL,
                source_email__iexact=session.email,
            )
            .select_related("issue", "issue__state", "project")
            .order_by("-created_at")[:MAX_TICKETS]
        )

        tickets = [
            {
                "id": str(intake_issue.issue_id),
                "name": intake_issue.issue.name,
                "sequence_id": intake_issue.issue.sequence_id,
                "priority": intake_issue.issue.priority,
                "created_at": intake_issue.created_at,
                "project_name": intake_issue.project.name if intake_issue.project else "",
                "state": intake_issue.issue.state.name if intake_issue.issue.state_id else None,
                "state_group": intake_issue.issue.state.group if intake_issue.issue.state_id else None,
                "intake_status": intake_issue.status,
            }
            for intake_issue in intake_issues
        ]
        return Response({"email": session.email, "tickets": tickets}, status=status.HTTP_200_OK)


class IntakePortalTicketDetailEndpoint(BaseAPIView):
    """Return a single ticket owned by the authenticated requester."""

    permission_classes = [AllowAny]

    def get(self, request, anchor, issue_id):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = resolve_session(request, portal.workspace_id)
        if session is None:
            return Response({"error": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED)

        # Ownership is enforced through the verified email, never through the id alone.
        intake_issue = (
            IntakeIssue.objects.filter(
                issue_id=issue_id,
                workspace_id=portal.workspace_id,
                source=SourceType.PORTAL,
                source_email__iexact=session.email,
            )
            .select_related("issue", "issue__state", "project")
            .first()
        )
        if intake_issue is None:
            return Response({"error": "Chamado não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        issue = intake_issue.issue
        comments = (
            IssueComment.objects.filter(issue_id=issue.id, access="EXTERNAL")
            .order_by("created_at")
            .values("id", "comment_html", "created_at")
        )

        return Response(
            {
                "id": str(issue.id),
                "name": issue.name,
                "description_html": issue.description_html,
                "sequence_id": issue.sequence_id,
                "priority": issue.priority,
                "created_at": intake_issue.created_at,
                "project_name": intake_issue.project.name if intake_issue.project else "",
                "state": issue.state.name if issue.state_id else None,
                "state_group": issue.state.group if issue.state_id else None,
                "intake_status": intake_issue.status,
                "comments": list(comments),
            },
            status=status.HTTP_200_OK,
        )
