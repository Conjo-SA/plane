# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
import logging

# Django imports
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueDevelopmentLinkSerializer, ProjectGitHubSettingsSerializer
from plane.app.views.base import BaseAPIView
from plane.bgtasks.conjo_github_task import (
    LAST_EVENT_CACHE_KEY,
    compact_payload,
    process_github_event,
    record_last_event,
)
from plane.db.models import Issue, IssueDevelopmentLink, Project, ProjectGitHubSettings
from plane.utils.conjo_github import branch_name_for, is_configured, verify_signature

logger = logging.getLogger("plane.api")

HANDLED_EVENTS = ("push", "create", "delete", "pull_request")
DELIVERY_CACHE_TTL = 60 * 60 * 24


def webhook_url():
    return f"{settings.TASKS_PUBLIC_URL}/api/conjo/github/webhook/"


class GitHubWebhookEndpoint(APIView):
    """Receives GitHub webhooks (organization or repository) signed with the shared secret."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not is_configured():
            return Response({"error": "GitHub não configurado neste servidor."}, status=status.HTTP_404_NOT_FOUND)
        body = request.body
        if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
            return Response({"error": "Assinatura inválida."}, status=status.HTTP_401_UNAUTHORIZED)

        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            record_last_event(event, json.loads(body or b"{}"))
            return Response({"ok": True, "pong": True}, status=status.HTTP_200_OK)
        if event not in HANDLED_EVENTS:
            return Response({"ok": True, "ignored": event}, status=status.HTTP_200_OK)

        # GitHub may redeliver the same event; process each delivery once.
        delivery = request.headers.get("X-GitHub-Delivery")
        if delivery and not cache.add(f"conjo_github:delivery:{delivery}", 1, DELIVERY_CACHE_TTL):
            return Response({"ok": True, "duplicate": True}, status=status.HTTP_200_OK)

        try:
            payload = json.loads(body)
        except ValueError:
            return Response({"error": "JSON inválido."}, status=status.HTTP_400_BAD_REQUEST)
        data = compact_payload(event, payload)
        record_last_event(event, data or payload)
        if data is not None:
            process_github_event.delay(event, data)
        return Response({"ok": True}, status=status.HTTP_202_ACCEPTED)


def get_or_create_settings(slug, project_id):
    obj = ProjectGitHubSettings.objects.filter(workspace__slug=slug, project_id=project_id).first()
    if obj is not None:
        return obj
    project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
    if project is None:
        return None
    try:
        return ProjectGitHubSettings.objects.create(project=project)
    except IntegrityError:
        return ProjectGitHubSettings.objects.filter(workspace__slug=slug, project_id=project_id).first()


def settings_payload(obj):
    data = ProjectGitHubSettingsSerializer(obj).data
    data.update(
        webhook_configured=is_configured(),
        webhook_url=webhook_url(),
        last_event=cache.get(LAST_EVENT_CACHE_KEY),
        project_identifier=obj.project.identifier,
    )
    return data


class ProjectGitHubSettingsEndpoint(BaseAPIView):
    """Smart commits and pull request automations of a project."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        obj = get_or_create_settings(slug, project_id)
        if obj is None:
            return Response({"error": "Projeto não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(settings_payload(obj), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id):
        obj = get_or_create_settings(slug, project_id)
        if obj is None:
            return Response({"error": "Projeto não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        fields = ("smart_commits", "pr_opened_state", "pr_merged_state")
        payload = {field: request.data[field] for field in fields if field in request.data}
        serializer = ProjectGitHubSettingsSerializer(obj, data=payload, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(settings_payload(obj), status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class IssueDevelopmentEndpoint(BaseAPIView):
    """Branches, commits and pull requests linked to a work item (the "Desenvolvimento" panel)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        issue = (
            Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id)
            .select_related("project")
            .first()
        )
        if issue is None:
            return Response({"error": "Tarefa não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        links = IssueDevelopmentLink.objects.filter(issue=issue)
        grouped = {"branches": [], "commits": [], "pull_requests": []}
        group_for = {"branch": "branches", "commit": "commits", "pull_request": "pull_requests"}
        for link in IssueDevelopmentLinkSerializer(links, many=True).data:
            grouped[group_for[link["kind"]]].append(link)
        return Response(
            {
                **grouped,
                "branch_name": branch_name_for(issue.project.identifier, issue.sequence_id, issue.name),
                "github_configured": is_configured(),
            },
            status=status.HTTP_200_OK,
        )
