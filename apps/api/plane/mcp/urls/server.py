# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.mcp.views import MCPServerEndpoint

urlpatterns = [
    path(
        "server/",
        MCPServerEndpoint.as_view(),
        name="mcp-server",
    ),
]
