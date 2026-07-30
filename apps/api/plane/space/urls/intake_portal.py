# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.space.views import IntakePortalMetaEndpoint, IntakePortalWorkItemEndpoint


urlpatterns = [
    path(
        "intake-portal/<str:anchor>/",
        IntakePortalMetaEndpoint.as_view(),
        name="intake-portal-meta",
    ),
    path(
        "intake-portal/<str:anchor>/work-items/",
        IntakePortalWorkItemEndpoint.as_view(),
        name="intake-portal-work-items",
    ),
]
