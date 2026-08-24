# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.mcp.models import MCPServer, MCPToolCallLog


class MCPServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPServer
        fields = [
            "id",
            "name",
            "description",
            "is_enabled",
            "token",
            "disabled_tools",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "token", "created_at", "updated_at"]


class MCPToolCallLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPToolCallLog
        fields = [
            "id",
            "tool_name",
            "arguments",
            "status",
            "error_message",
            "duration_ms",
            "created_at",
        ]
        read_only_fields = fields
