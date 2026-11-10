# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.conjo_areas import (
    WorkspaceAreaAccessEndpoint,
    WorkspaceAreaOverrideDetailEndpoint,
    WorkspaceAreaOverridesEndpoint,
    WorkspaceMyAreasEndpoint,
)

AREAS = "workspaces/<str:slug>/area-access"

urlpatterns = [
    path(f"{AREAS}/", WorkspaceAreaAccessEndpoint.as_view(), name="workspace-area-access"),
    path(f"{AREAS}/me/", WorkspaceMyAreasEndpoint.as_view(), name="workspace-area-access-me"),
    path(f"{AREAS}/overrides/", WorkspaceAreaOverridesEndpoint.as_view(), name="workspace-area-overrides"),
    path(
        f"{AREAS}/overrides/<uuid:override_id>/",
        WorkspaceAreaOverrideDetailEndpoint.as_view(),
        name="workspace-area-override",
    ),
]
