# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from django.utils.html import escape, strip_tags

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

# Module imports
from plane.bgtasks.intake_portal_task import send_portal_verification_code
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import FileAsset, IntakeIssue, IntakePortalBudget, IssueAssignee, IssueComment, IssueLabel
from plane.db.models.intake import IntakePortalBudgetStatus, SourceType
from plane.settings.storage import S3Storage
from plane.utils.content_validator import validate_html_content
from plane.utils.intake_portal import serialize_portal_budget
from plane.utils.mailjet import is_email_provider_configured
from plane.utils.uuid import is_valid_uuid

from .base import BaseAPIView
from .intake_portal import MAX_ATTACHMENTS, get_enabled_portal
from .portal_auth import (
    create_session,
    create_verification,
    is_on_cooldown,
    normalize_email,
    resolve_session,
    verify_code,
)

MAX_TICKETS = 100
MAX_COMMENT_HTML_LENGTH = 20000

# Marks the replies an external requester wrote from the portal, so the portal
# can tell them apart from the ones written by the support team.
PORTAL_COMMENT_SOURCE = "INTAKE_PORTAL"


def get_owned_intake_issue(portal, issue_id, email):
    """Return the ticket owned by the verified requester, or None.

    Ownership is always resolved through the verified email, never through the
    work item id alone, so a guessed id cannot expose someone else's ticket.
    """
    if not is_valid_uuid(str(issue_id)):
        return None

    return (
        IntakeIssue.objects.filter(
            issue_id=issue_id,
            workspace_id=portal.workspace_id,
            source=SourceType.PORTAL,
            source_email__iexact=email,
        )
        .select_related("issue", "issue__state", "project")
        .first()
    )


def serialize_ticket_comments(issue_id):
    """Public conversation of a ticket. Internal notes are never exposed."""
    comments = (
        IssueComment.objects.filter(issue_id=issue_id, access="EXTERNAL")
        .select_related("actor")
        .order_by("created_at")
    )

    return [
        {
            "id": str(comment.id),
            "comment_html": comment.comment_html,
            "created_at": comment.created_at,
            "is_requester": comment.external_source == PORTAL_COMMENT_SOURCE,
            "author": (
                "Você"
                if comment.external_source == PORTAL_COMMENT_SOURCE
                else (comment.actor.display_name if comment.actor_id else "Equipe de atendimento")
            ),
        }
        for comment in comments
    ]


def serialize_ticket_attachments(anchor, issue_id):
    """Files attached to the ticket, with a portal scoped download route."""
    assets = FileAsset.objects.filter(
        issue_id=issue_id,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        is_uploaded=True,
        is_deleted=False,
    ).order_by("created_at")

    return [
        {
            "id": str(asset.id),
            "name": (asset.attributes or {}).get("name") or "arquivo",
            "type": (asset.attributes or {}).get("type") or "",
            "size": asset.size,
            "created_at": asset.created_at,
            "download_url": f"/api/public/intake-portal/{anchor}/tickets/{issue_id}/attachments/{asset.id}/",
        }
        for asset in assets
    ]


def link_portal_assets(portal, issue_id, attachment_ids):
    """Attach portal uploads to a ticket.

    Only unlinked assets uploaded into this portal's project are claimed, so a
    crafted payload can never steal a file that belongs to another work item.
    """
    asset_ids = [asset_id for asset_id in attachment_ids if is_valid_uuid(str(asset_id))]
    if not asset_ids:
        return

    FileAsset.objects.filter(
        id__in=asset_ids,
        workspace_id=portal.workspace_id,
        project_id=portal.project_id,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        issue__isnull=True,
        is_uploaded=True,
    ).update(issue_id=issue_id)


def serialize_ticket_labels(issue_id):
    """Labels applied to the ticket, so the requester sees how it was classified."""
    labels = (
        IssueLabel.objects.filter(issue_id=issue_id)
        .select_related("label")
        .values("label__name", "label__color")
    )
    return [
        {"name": label["label__name"], "color": label["label__color"]}
        for label in labels
        if label["label__name"]
    ]


def serialize_ticket_assignees(issue_id):
    """Names of the people handling the ticket."""
    assignees = (
        IssueAssignee.objects.filter(issue_id=issue_id)
        .select_related("assignee")
        .values_list("assignee__display_name", flat=True)
    )
    return [display_name for display_name in assignees if display_name]


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

        # Fail loudly instead of promising a code that no provider can deliver.
        if not is_email_provider_configured():
            return Response(
                {"error": "O envio de e-mails não está configurado. Avise o administrador."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

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
        intake_issue = get_owned_intake_issue(portal, issue_id, session.email)
        if intake_issue is None:
            return Response({"error": "Chamado não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        issue = intake_issue.issue

        return Response(
            {
                "id": str(issue.id),
                "name": issue.name,
                "description_html": issue.description_html,
                "sequence_id": issue.sequence_id,
                "project_identifier": intake_issue.project.identifier if intake_issue.project else "",
                "priority": issue.priority,
                "created_at": intake_issue.created_at,
                "updated_at": issue.updated_at,
                "target_date": issue.target_date,
                "completed_at": issue.completed_at,
                "project_name": intake_issue.project.name if intake_issue.project else "",
                "state": issue.state.name if issue.state_id else None,
                "state_group": issue.state.group if issue.state_id else None,
                "intake_status": intake_issue.status,
                "is_attachment_enabled": portal.is_attachment_enabled,
                "labels": serialize_ticket_labels(issue.id),
                "assignees": serialize_ticket_assignees(issue.id),
                "budget": serialize_portal_budget(IntakePortalBudget.objects.filter(issue_id=issue.id).first()),
                "comments": serialize_ticket_comments(issue.id),
                "attachments": serialize_ticket_attachments(anchor, issue.id),
            },
            status=status.HTTP_200_OK,
        )


class IntakePortalTicketCommentEndpoint(BaseAPIView):
    """Let the requester reply on their own ticket from the portal."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "intake_portal"

    def post(self, request, anchor, issue_id):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = resolve_session(request, portal.workspace_id)
        if session is None:
            return Response({"error": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED)

        intake_issue = get_owned_intake_issue(portal, issue_id, session.email)
        if intake_issue is None:
            return Response({"error": "Chamado não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        # Sanitize before saving to prevent stored XSS on the agent side too.
        _, _, sanitized_comment_html = validate_html_content(request.data.get("comment_html", ""))
        comment_html = sanitized_comment_html or ""
        if not strip_tags(comment_html).strip():
            return Response(
                {"error": "Escreva uma mensagem antes de enviar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(comment_html) > MAX_COMMENT_HTML_LENGTH:
            return Response(
                {"error": "Sua mensagem é muito longa."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attachment_ids = request.data.get("attachment_ids") or []
        if not isinstance(attachment_ids, list):
            return Response({"error": "Invalid attachments"}, status=status.HTTP_400_BAD_REQUEST)
        if len(attachment_ids) > MAX_ATTACHMENTS:
            return Response(
                {"error": f"Você pode anexar no máximo {MAX_ATTACHMENTS} arquivos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        comment = IssueComment.objects.create(
            issue_id=intake_issue.issue_id,
            project_id=portal.project_id,
            workspace_id=portal.workspace_id,
            comment_html=comment_html,
            # Replies written from the portal are always part of the public thread.
            access="EXTERNAL",
            external_source=PORTAL_COMMENT_SOURCE,
            external_id=session.email,
        )

        if attachment_ids and portal.is_attachment_enabled:
            link_portal_assets(portal, intake_issue.issue_id, attachment_ids)

        issue_activity.delay(
            type="comment.activity.created",
            requested_data=json.dumps(
                {"id": str(comment.id), "comment_html": comment.comment_html}, cls=DjangoJSONEncoder
            ),
            actor_id=None,
            issue_id=str(intake_issue.issue_id),
            project_id=str(portal.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
        )

        return Response(
            {
                "id": str(comment.id),
                "comment_html": comment.comment_html,
                "created_at": comment.created_at,
                "is_requester": True,
                "author": "Você",
            },
            status=status.HTTP_201_CREATED,
        )


class IntakePortalTicketAttachmentEndpoint(BaseAPIView):
    """Attach portal uploads to an existing ticket and hand out download links."""

    permission_classes = [AllowAny]
    throttle_scope = "intake_portal"

    def get_throttles(self):
        # Resolving a download link is a session scoped read, so only the write
        # path carries the anonymous rate limit.
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return []

    def post(self, request, anchor, issue_id):
        portal = get_enabled_portal(anchor)
        if portal is None or not portal.is_attachment_enabled:
            return Response(
                {"error": "Attachments are not available for this request form."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = resolve_session(request, portal.workspace_id)
        if session is None:
            return Response({"error": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED)

        intake_issue = get_owned_intake_issue(portal, issue_id, session.email)
        if intake_issue is None:
            return Response({"error": "Chamado não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        attachment_ids = request.data.get("attachment_ids") or []
        if not isinstance(attachment_ids, list) or not attachment_ids:
            return Response({"error": "Invalid attachments"}, status=status.HTTP_400_BAD_REQUEST)
        if len(attachment_ids) > MAX_ATTACHMENTS:
            return Response(
                {"error": f"Você pode anexar no máximo {MAX_ATTACHMENTS} arquivos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        link_portal_assets(portal, intake_issue.issue_id, attachment_ids)

        return Response(
            {"attachments": serialize_ticket_attachments(anchor, intake_issue.issue_id)},
            status=status.HTTP_200_OK,
        )

    def get(self, request, anchor, issue_id, pk):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = resolve_session(request, portal.workspace_id)
        if session is None:
            return Response({"error": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED)

        intake_issue = get_owned_intake_issue(portal, issue_id, session.email)
        if intake_issue is None:
            return Response({"error": "Chamado não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        # Scope the asset to the ticket so an id from another work item cannot be read.
        asset = FileAsset.objects.filter(
            pk=pk,
            issue_id=intake_issue.issue_id,
            workspace_id=portal.workspace_id,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            is_uploaded=True,
            is_deleted=False,
        ).first()
        if asset is None:
            return Response({"error": "Anexo não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        # Force a download for script capable types so the file can never execute
        # on the portal's own origin.
        asset_mime_type = ((asset.attributes or {}).get("type") or "").split(";")[0].strip().lower()
        disposition = "attachment" if asset_mime_type in settings.SCRIPT_CAPABLE_MIME_TYPES else "inline"

        storage = S3Storage(request=request)
        signed_url = storage.generate_presigned_url(
            object_name=asset.asset.name,
            disposition=disposition,
            filename=(asset.attributes or {}).get("name"),
        )
        if signed_url is None:
            return Response(
                {"error": "Não foi possível abrir o anexo. Tente novamente."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"url": signed_url}, status=status.HTTP_200_OK)


class IntakePortalTicketBudgetEndpoint(BaseAPIView):
    """Approval of an hourly estimate by the requester who owns the ticket."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "intake_portal"

    def post(self, request, anchor, issue_id):
        portal = get_enabled_portal(anchor)
        if portal is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = resolve_session(request, portal.workspace_id)
        if session is None:
            return Response({"error": "Sessão expirada."}, status=status.HTTP_401_UNAUTHORIZED)

        intake_issue = get_owned_intake_issue(portal, issue_id, session.email)
        if intake_issue is None:
            return Response({"error": "Chamado não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        budget = IntakePortalBudget.objects.filter(issue_id=intake_issue.issue_id).first()
        if budget is None:
            return Response(
                {"error": "Não há orçamento para aprovar neste chamado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Approval is one way on purpose: it can never be repeated or undone.
        # The conditional update is what enforces it, so two concurrent clicks
        # cannot both win and approve the same estimate twice.
        approved_count = IntakePortalBudget.objects.filter(
            pk=budget.pk, status=IntakePortalBudgetStatus.PENDING
        ).update(
            status=IntakePortalBudgetStatus.APPROVED,
            approved_at=timezone.now(),
            approved_by_email=session.email,
        )
        if not approved_count:
            return Response(
                {"error": "Este orçamento já foi aprovado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        budget.refresh_from_db()

        hours = f"{budget.estimated_hours:.2f}".rstrip("0").rstrip(".")
        comment = IssueComment.objects.create(
            issue_id=intake_issue.issue_id,
            project_id=portal.project_id,
            workspace_id=portal.workspace_id,
            comment_html=(
                f"<p>Orçamento de {escape(hours)} horas aprovado por {escape(session.email)}.</p>"
            ),
            access="EXTERNAL",
            external_source=PORTAL_COMMENT_SOURCE,
            external_id=session.email,
        )

        # Surfaces the approval on the work item timeline for the team.
        issue_activity.delay(
            type="comment.activity.created",
            requested_data=json.dumps(
                {"id": str(comment.id), "comment_html": comment.comment_html}, cls=DjangoJSONEncoder
            ),
            actor_id=None,
            issue_id=str(intake_issue.issue_id),
            project_id=str(portal.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
        )

        return Response(serialize_portal_budget(budget), status=status.HTTP_200_OK)
