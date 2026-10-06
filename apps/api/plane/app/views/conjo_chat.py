# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging

# Django imports
from django.db import IntegrityError
from django.utils.html import escape

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import ProjectChatIntegrationSerializer
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ProjectChatIntegration
from plane.utils.conjo_chat import MatrixError, create_project_room, is_configured, send_html_message

logger = logging.getLogger("plane.api")

EDITABLE_FIELDS = [
    "enabled",
    "notify_issue_created",
    "notify_state_changed",
    "notify_assignee_changed",
    "notify_comment_created",
]

NOT_CONFIGURED_ERROR = "Chat não configurado neste servidor."


def get_or_create_integration(slug, project_id):
    integration = ProjectChatIntegration.objects.filter(workspace__slug=slug, project_id=project_id).first()
    if integration is not None:
        return integration
    project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
    if project is None:
        return None
    try:
        return ProjectChatIntegration.objects.create(project=project, workspace_id=project.workspace_id)
    except IntegrityError:
        # A concurrent request created it first.
        return ProjectChatIntegration.objects.filter(workspace__slug=slug, project_id=project_id).first()


class ProjectChatIntegrationEndpoint(BaseAPIView):
    """Configure the Conjo Chat room that receives the project's work item notices."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        integration = get_or_create_integration(slug, project_id)
        if integration is None:
            return Response({"error": "Projeto não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProjectChatIntegrationSerializer(integration).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id):
        integration = get_or_create_integration(slug, project_id)
        if integration is None:
            return Response({"error": "Projeto não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        payload = {field: request.data[field] for field in EDITABLE_FIELDS if field in request.data}
        serializer = ProjectChatIntegrationSerializer(integration, data=payload, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProjectChatIntegrationRoomEndpoint(BaseAPIView):
    """Create the project room in the chat, or refresh it when it already exists."""

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        if not is_configured():
            return Response({"error": NOT_CONFIGURED_ERROR}, status=status.HTTP_400_BAD_REQUEST)
        integration = get_or_create_integration(slug, project_id)
        if integration is None:
            return Response({"error": "Projeto não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        project = Project.objects.select_related("workspace").get(pk=integration.project_id)
        try:
            room_id, room_name = create_project_room(project, room_id=integration.room_id)
        except MatrixError as e:
            logger.warning("conjo_chat: create room failed for project %s: %s", project_id, e)
            return Response(
                {"error": f"Não foi possível criar a sala no chat: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        integration.room_id = room_id
        integration.room_name = room_name
        integration.enabled = True
        integration.save(update_fields=["room_id", "room_name", "enabled", "updated_at", "updated_by"])
        return Response(ProjectChatIntegrationSerializer(integration).data, status=status.HTTP_200_OK)


class ProjectChatIntegrationTestEndpoint(BaseAPIView):
    """Send a test message to the project room."""

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        if not is_configured():
            return Response({"error": NOT_CONFIGURED_ERROR}, status=status.HTTP_400_BAD_REQUEST)
        integration = ProjectChatIntegration.objects.filter(
            workspace__slug=slug, project_id=project_id
        ).select_related("project").first()
        if integration is None or not integration.room_id:
            return Response(
                {"error": "Crie a sala do projeto no chat antes de enviar um teste."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project_name = integration.project.name
        html = (
            f"Mensagem de teste do <b>Conjo Tasks</b>: os avisos do projeto "
            f"<b>{escape(project_name)}</b> chegarão nesta sala."
        )
        body = f"Mensagem de teste do Conjo Tasks: os avisos do projeto {project_name} chegarão nesta sala."
        try:
            send_html_message(integration.room_id, html, body)
        except MatrixError as e:
            logger.warning("conjo_chat: test message failed for project %s: %s", project_id, e)
            return Response(
                {"error": f"Não foi possível enviar a mensagem de teste: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"ok": True}, status=status.HTTP_200_OK)
