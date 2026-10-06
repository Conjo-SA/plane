# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    GitHubWebhookEndpoint,
    IssueDevelopmentEndpoint,
    ProjectGitHubSettingsEndpoint,
    ProjectGitHubSyncEndpoint,
    ProjectDevelopmentSummaryEndpoint,
)


urlpatterns = [
    path("conjo/github/webhook/", GitHubWebhookEndpoint.as_view(), name="conjo-github-webhook"),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/github-integration/",
        ProjectGitHubSettingsEndpoint.as_view(),
        name="project-github-integration",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/github-integration/sync/",
        ProjectGitHubSyncEndpoint.as_view(),
        name="project-github-integration-sync",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/development/",
        IssueDevelopmentEndpoint.as_view(),
        name="issue-development",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/development-summary/",
        ProjectDevelopmentSummaryEndpoint.as_view(),
        name="project-development-summary",
    ),
]
