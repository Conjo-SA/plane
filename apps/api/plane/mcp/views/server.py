# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hmac

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

# Module imports
from plane.mcp.models import MCPServer
from plane.mcp.server import PROTOCOL_VERSION, SERVER_INFO, handle_mcp_payload


def _token_matches(authorization, server):
    """Constant-time check of `Authorization: Bearer <token>`.

    Compared as bytes: `hmac.compare_digest` raises TypeError on non-ASCII str, which turned a crafted
    header into a 500 instead of a 401.
    """
    scheme, _, token = (authorization or "").partition(" ")
    if not server or scheme.lower() != "bearer" or not token or not server.token:
        return False
    return hmac.compare_digest(token.strip().encode("utf-8"), server.token.encode("utf-8"))


def _bearer_is_valid(request):
    return _token_matches(request.headers.get("Authorization", ""), MCPServer.get_instance())


class MCPThrottle(SimpleRateThrottle):
    """An agent organizing the board makes many calls in a row: the valid token gets a generous budget,
    while anything else stays at the anonymous rate per IP (which also slows down token guessing)."""

    TOKEN_RATE = "600/minute"
    ANONYMOUS_RATE = "30/minute"

    def get_rate(self):
        return self.ANONYMOUS_RATE

    def allow_request(self, request, view):
        self._valid = _bearer_is_valid(request)
        self.rate = self.TOKEN_RATE if self._valid else self.ANONYMOUS_RATE
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if self._valid:
            return "throttle_mcp_token"
        return f"throttle_mcp_anon_{self.get_ident(request)}"


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
    throttle_classes = [MCPThrottle]

    def _authenticate(self, request):
        """Return (server, error_response)."""
        server = MCPServer.get_instance()
        if server is None:
            return None, Response(
                {"error": "MCP server is not configured on this instance"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _token_matches(request.headers.get("Authorization", ""), server):
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
