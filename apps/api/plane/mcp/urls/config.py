# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.mcp.views import (
    MCPConfigEndpoint,
    MCPTestConnectionEndpoint,
    MCPTokenRegenerateEndpoint,
    MCPToolCallLogsEndpoint,
    MCPToolsEndpoint,
)

urlpatterns = [
    path(
        "config/",
        MCPConfigEndpoint.as_view(),
        name="mcp-config",
    ),
    path(
        "config/regenerate-token/",
        MCPTokenRegenerateEndpoint.as_view(),
        name="mcp-config-regenerate-token",
    ),
    path(
        "tools/",
        MCPToolsEndpoint.as_view(),
        name="mcp-tools",
    ),
    path(
        "test/",
        MCPTestConnectionEndpoint.as_view(),
        name="mcp-test-connection",
    ),
    path(
        "logs/",
        MCPToolCallLogsEndpoint.as_view(),
        name="mcp-tool-call-logs",
    ),
]
