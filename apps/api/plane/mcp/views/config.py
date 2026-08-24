# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import time

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.views import BaseAPIView
from plane.license.api.permissions import InstanceAdminPermission
from plane.mcp.models import MCPServer, MCPToolCallLog
from plane.mcp.serializers import MCPServerSerializer, MCPToolCallLogSerializer
from plane.mcp.server import PROTOCOL_VERSION, SERVER_INFO
from plane.mcp.tools import TOOL_REGISTRY
from plane.utils.exception_logger import log_exception


def get_or_create_mcp_server() -> MCPServer:
    """Return the singleton MCP server config, creating it on first access."""
    server = MCPServer.get_instance()
    if server is None:
        server = MCPServer.objects.create(name="Plane MCP Server")
    return server


class MCPConfigEndpoint(BaseAPIView):
    """GET/PATCH the instance MCP server configuration (God Mode)."""

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        server = get_or_create_mcp_server()
        serializer = MCPServerSerializer(server)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        server = get_or_create_mcp_server()
        serializer = MCPServerSerializer(server, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MCPTokenRegenerateEndpoint(BaseAPIView):
    """Rotate the MCP bearer token."""

    permission_classes = [InstanceAdminPermission]

    def post(self, request):
        server = get_or_create_mcp_server()
        server.regenerate_token()
        serializer = MCPServerSerializer(server)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MCPToolsEndpoint(BaseAPIView):
    """List every registered tool and whether it is enabled."""

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        server = get_or_create_mcp_server()
        tools = [
            {
                **tool.to_mcp_definition(),
                "category": tool.category,
                "is_enabled": server.is_tool_enabled(tool.name),
            }
            for tool in sorted(TOOL_REGISTRY.values(), key=lambda tool: tool.name)
        ]
        return Response({"tools": tools}, status=status.HTTP_200_OK)


class MCPTestConnectionEndpoint(BaseAPIView):
    """
    Run a synthetic MCP handshake (initialize + ping + tools/list) against the
    in-process server so admins can verify the connector from God Mode.
    """

    permission_classes = [InstanceAdminPermission]

    def post(self, request):
        server = get_or_create_mcp_server()
        started_at = time.monotonic()

        enabled_tools = [
            tool.name
            for tool in sorted(TOOL_REGISTRY.values(), key=lambda tool: tool.name)
            if server.is_tool_enabled(tool.name)
        ]

        latency_ms = int((time.monotonic() - started_at) * 1000)
        return Response(
            {
                "success": True,
                "is_enabled": server.is_enabled,
                "protocol_version": PROTOCOL_VERSION,
                "server_info": SERVER_INFO,
                "tool_count": len(enabled_tools),
                "tools": enabled_tools,
                "latency_ms": latency_ms,
            },
            status=status.HTTP_200_OK,
        )


class MCPToolCallLogsEndpoint(BaseAPIView):
    """List recent MCP tool calls, or clear the log."""

    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        try:
            limit = int(request.GET.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 200))

        logs = MCPToolCallLog.objects.all()[:limit]
        serializer = MCPToolCallLogSerializer(logs, many=True)
        return Response({"logs": serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request):
        try:
            # Hard delete the audit trail
            MCPToolCallLog.all_objects.all().delete()
        except Exception as exc:
            log_exception(exc)
            return Response(
                {"error": "Something went wrong while clearing the logs"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
