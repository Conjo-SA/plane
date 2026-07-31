# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.space.views import (
    IntakePortalAssetEndpoint,
    IntakePortalMetaEndpoint,
    IntakePortalTicketAttachmentEndpoint,
    IntakePortalTicketBudgetEndpoint,
    IntakePortalTicketCommentEndpoint,
    IntakePortalTicketDetailEndpoint,
    IntakePortalTicketsEndpoint,
    IntakePortalVerificationConfirmEndpoint,
    IntakePortalVerificationEndpoint,
    IntakePortalWorkItemEndpoint,
)


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
    path(
        "intake-portal/<str:anchor>/assets/",
        IntakePortalAssetEndpoint.as_view(),
        name="intake-portal-assets",
    ),
    path(
        "intake-portal/<str:anchor>/assets/<uuid:pk>/",
        IntakePortalAssetEndpoint.as_view(),
        name="intake-portal-asset",
    ),
    path(
        "intake-portal/<str:anchor>/verify/",
        IntakePortalVerificationEndpoint.as_view(),
        name="intake-portal-verify",
    ),
    path(
        "intake-portal/<str:anchor>/verify/confirm/",
        IntakePortalVerificationConfirmEndpoint.as_view(),
        name="intake-portal-verify-confirm",
    ),
    path(
        "intake-portal/<str:anchor>/tickets/",
        IntakePortalTicketsEndpoint.as_view(),
        name="intake-portal-tickets",
    ),
    path(
        "intake-portal/<str:anchor>/tickets/<uuid:issue_id>/",
        IntakePortalTicketDetailEndpoint.as_view(),
        name="intake-portal-ticket-detail",
    ),
    path(
        "intake-portal/<str:anchor>/tickets/<uuid:issue_id>/comments/",
        IntakePortalTicketCommentEndpoint.as_view(),
        name="intake-portal-ticket-comments",
    ),
    path(
        "intake-portal/<str:anchor>/tickets/<uuid:issue_id>/attachments/",
        IntakePortalTicketAttachmentEndpoint.as_view(),
        name="intake-portal-ticket-attachments",
    ),
    path(
        "intake-portal/<str:anchor>/tickets/<uuid:issue_id>/attachments/<uuid:pk>/",
        IntakePortalTicketAttachmentEndpoint.as_view(),
        name="intake-portal-ticket-attachment",
    ),
    path(
        "intake-portal/<str:anchor>/tickets/<uuid:issue_id>/budget/approve/",
        IntakePortalTicketBudgetEndpoint.as_view(),
        name="intake-portal-ticket-budget-approve",
    ),
]
