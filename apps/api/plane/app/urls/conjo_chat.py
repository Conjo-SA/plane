# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ProjectChatIntegrationEndpoint,
    ProjectChatIntegrationRoomEndpoint,
    ProjectChatIntegrationTestEndpoint,
)


urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/chat-integration/",
        ProjectChatIntegrationEndpoint.as_view(),
        name="project-chat-integration",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/chat-integration/create-room/",
        ProjectChatIntegrationRoomEndpoint.as_view(),
        name="project-chat-integration-create-room",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/chat-integration/test/",
        ProjectChatIntegrationTestEndpoint.as_view(),
        name="project-chat-integration-test",
    ),
]
