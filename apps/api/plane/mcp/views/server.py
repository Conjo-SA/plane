# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from plane.mcp.models import MCPServer
from plane.mcp.server import PROTOCOL_VERSION, SERVER_INFO, handle_mcp_payload


class MCPServerEndpoint(APIView):
    """
    MCP protocol endpoint (JSON-RPC 2.0 over HTTP POST).

    Authentication is token based: clients send the instance MCP token as
    `Authorization: Bearer plane_mcp_<token>`. Session/CSRF authentication is
    intentionally disabled — this endpoint is consumed by MCP clients, not
    browsers.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def _authenticate(self, request):
        """Return (server, error_response)."""
        server = MCPServer.get_instance()
        if server is None:
            return None, Response(
                {"error": "MCP server is not configured on this instance"},
                status=status.HTTP_404_NOT_FOUND,
            )

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or token != server.token:
            return None, Response(
                {"error": "Invalid or missing MCP bearer token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not server.is_enabled:
            return None, Response(
                {"error": "MCP server is disabled on this instance"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return server, None

    def post(self, request):
        server, error_response = self._authenticate(request)
        if error_response is not None:
            return error_response

        response, response_status = handle_mcp_payload(request.data, server)
        if response is None:
            return Response(status=response_status)
        return Response(response, status=response_status)

    def get(self, request):
        """Lightweight discovery payload for MCP clients and health checks."""
        server, error_response = self._authenticate(request)
        if error_response is not None:
            return error_response

        return Response(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "isEnabled": server.is_enabled,
            },
            status=status.HTTP_200_OK,
        )
