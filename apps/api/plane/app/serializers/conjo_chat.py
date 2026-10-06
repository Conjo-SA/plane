# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import ProjectChatIntegration
from plane.utils.conjo_chat import is_configured, room_url

from .base import BaseSerializer


class ProjectChatIntegrationSerializer(BaseSerializer):
    room_url = serializers.SerializerMethodField()
    chat_configured = serializers.SerializerMethodField()

    class Meta:
        model = ProjectChatIntegration
        fields = [
            "id",
            "project",
            "enabled",
            "room_id",
            "room_name",
            "room_url",
            "notify_issue_created",
            "notify_state_changed",
            "notify_assignee_changed",
            "notify_comment_created",
            "chat_configured",
        ]
        read_only_fields = ["id", "project", "room_id", "room_name"]

    def get_room_url(self, obj):
        return room_url(obj.room_id)

    def get_chat_configured(self, obj):
        return is_configured()
