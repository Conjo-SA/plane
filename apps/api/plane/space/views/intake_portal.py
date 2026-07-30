# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
import uuid

# Django imports
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.db.models import Q
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.bgtasks.intake_portal_task import send_portal_ticket_created
from plane.bgtasks.storage_metadata_task import get_asset_object_metadata
from plane.db.models import FileAsset, IntakeIssue, IntakePortal, Issue, IssueLabel, Label, State, StateGroup
from plane.db.models.intake import SourceType
from plane.settings.storage import S3Storage
from plane.utils.content_validator import validate_html_content
from plane.utils.path_validator import sanitize_filename
from plane.utils.uuid import is_valid_uuid

from .base import BaseAPIView
from .portal_auth import resolve_session

VALID_PRIORITIES = ["urgent", "high", "medium", "low", "none"]
MAX_NAME_LENGTH = 255
MAX_REQUESTER_NAME_LENGTH = 120
MAX_ATTACHMENTS = 10

# Attachment types accepted from anonymous requesters. Script-capable types
# (html, svg, js) are intentionally excluded to avoid stored XSS on download.
ALLOWED_ATTACHMENT_TYPES = {
    # images
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    # video
    "video/mp4",
    "video/webm",
    "video/quicktime",
    # documents
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # archives
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/gzip",
}


def get_enabled_portal(anchor):
    """Return the enabled portal matching the anchor or its custom slug."""
    return (
        IntakePortal.objects.filter(Q(anchor=anchor) | Q(slug__iexact=anchor), is_enabled=True)
        .select_related("project", "workspace", "intake")
        .first()
    )


def resolve_portal_label(portal, tag):
    """Resolve a URL tag to an existing project label.

    Only labels that already exist in the project are accepted, so anonymous
    submissions can never create new labels. Matching is case-insensitive and
    tolerates hyphen/underscore separators used in URLs.
    """
    if not tag:
        return None

    normalized = tag.strip()
    candidates = [normalized, normalized.replace("-", " "), normalized.replace("_", " ")]

    for candidate in candidates:
        label = Label.objects.filter(project_id=portal.project_id, name__iexact=candidate).first()
        if label:
            return label
    return None


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

        tag = request.query_params.get("tag")
        label = resolve_portal_label(portal, tag)
        if tag and label is None:
            return Response(
                {"error": "This request form is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "anchor": portal.anchor,
                "slug": portal.slug,
                "title": portal.title or portal.project.name,
                "description": portal.description,
                "success_message": portal.success_message,
                "is_attachment_enabled": portal.is_attachment_enabled,
                "project_name": portal.project.name,
                "workspace_name": portal.workspace.name,
                "logo_props": portal.project.logo_props,
                "tag": {"id": str(label.id), "name": label.name, "color": label.color} if label else None,
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

        # The submission is only accepted for an address the requester has proven to own.
        session = resolve_session(request, portal.workspace_id)
        if session is None or session.email.lower() != requester_email.lower():
            return Response(
                {"error": "Confirme seu e-mail antes de enviar a solicitação."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        requester_name = (request.data.get("requester_name") or "").strip()[:MAX_REQUESTER_NAME_LENGTH]

        tag = request.data.get("tag")
        label = resolve_portal_label(portal, tag)
        if tag and label is None:
            return Response({"error": "Invalid tag"}, status=status.HTTP_400_BAD_REQUEST)

        attachment_ids = request.data.get("attachment_ids") or []
        if not isinstance(attachment_ids, list):
            return Response({"error": "Invalid attachments"}, status=status.HTTP_400_BAD_REQUEST)
        if len(attachment_ids) > MAX_ATTACHMENTS:
            return Response(
                {"error": f"You can attach at most {MAX_ATTACHMENTS} files"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        attachment_ids = [asset_id for asset_id in attachment_ids if is_valid_uuid(str(asset_id))]

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

        if label:
            IssueLabel.objects.create(
                issue=issue,
                label=label,
                project_id=portal.project_id,
                workspace_id=portal.workspace_id,
            )

        if attachment_ids:
            # Only claim assets uploaded through this portal that are not linked to
            # another work item yet, so a crafted payload cannot steal existing files.
            FileAsset.objects.filter(
                id__in=attachment_ids,
                workspace_id=portal.workspace_id,
                project_id=portal.project_id,
                entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
                issue__isnull=True,
                is_uploaded=True,
            ).update(issue_id=issue.id)

        issue_activity.delay(
            type="issue.activity.created",
            requested_data=json.dumps({"name": name, "priority": priority}, cls=DjangoJSONEncoder),
            actor_id=None,
            issue_id=str(issue.id),
            project_id=str(portal.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
        )

        send_portal_ticket_created.delay(str(issue.id))

        return Response(
            {
                "id": str(issue.id),
                "sequence_id": issue.sequence_id,
                "success_message": portal.success_message,
            },
            status=status.HTTP_201_CREATED,
        )


class IntakePortalAssetEndpoint(BaseAPIView):
    """Anonymous attachment upload for the public request form.

    Files go straight to object storage through a short-lived presigned POST, so
    the API never proxies the upload payload itself.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "intake_portal"

    def post(self, request, anchor):
        portal = get_enabled_portal(anchor)
        if portal is None or not portal.is_attachment_enabled:
            return Response(
                {"error": "Attachments are not available for this request form."},
                status=status.HTTP_404_NOT_FOUND,
            )

        name = sanitize_filename(request.data.get("name")) or "unnamed"
        file_type = (request.data.get("type") or "").split(";")[0].strip().lower()

        if file_type not in ALLOWED_ATTACHMENT_TYPES:
            return Response(
                {"error": "This file type is not supported."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            size = int(request.data.get("size", 0))
        except (TypeError, ValueError):
            return Response({"error": "Invalid file size"}, status=status.HTTP_400_BAD_REQUEST)

        if size <= 0 or size > int(settings.FILE_SIZE_LIMIT):
            return Response(
                {"error": "File exceeds the maximum allowed size."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        asset_key = f"{portal.workspace_id}/{uuid.uuid4().hex}-{name}"
        asset = FileAsset.objects.create(
            attributes={"name": name, "type": file_type, "size": size},
            asset=asset_key,
            size=size,
            workspace_id=portal.workspace_id,
            project_id=portal.project_id,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        )

        storage = S3Storage(request=request)
        presigned_url = storage.generate_presigned_post(object_name=asset_key, file_type=file_type, file_size=size)
        if presigned_url is None:
            asset.delete()
            return Response(
                {"error": "Could not prepare the upload. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {"upload_data": presigned_url, "asset_id": str(asset.id)},
            status=status.HTTP_200_OK,
        )

    def patch(self, request, anchor, pk):
        portal = get_enabled_portal(anchor)
        if portal is None or not portal.is_attachment_enabled:
            return Response(
                {"error": "Attachments are not available for this request form."},
                status=status.HTTP_404_NOT_FOUND,
            )

        asset = FileAsset.objects.filter(
            pk=pk,
            workspace_id=portal.workspace_id,
            project_id=portal.project_id,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            issue__isnull=True,
        ).first()
        if asset is None:
            return Response({"error": "Asset not found"}, status=status.HTTP_404_NOT_FOUND)

        asset.is_uploaded = True
        if not asset.storage_metadata:
            get_asset_object_metadata.delay(str(asset.id))
        asset.save(update_fields=["is_uploaded"])
        return Response(status=status.HTTP_204_NO_CONTENT)
