# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models

# Module imports
from .project import ProjectBaseModel


class IssueDevelopmentLink(ProjectBaseModel):
    """A GitHub branch, commit or pull request that mentions a work item (e.g. ``MAN-12``)."""

    KIND_BRANCH = "branch"
    KIND_COMMIT = "commit"
    KIND_PULL_REQUEST = "pull_request"
    KIND_CHOICES = (
        (KIND_BRANCH, "Branch"),
        (KIND_COMMIT, "Commit"),
        (KIND_PULL_REQUEST, "Pull request"),
    )

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="development_links")
    provider = models.CharField(max_length=30, default="github")
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    # "owner/name"
    repository = models.CharField(max_length=255)
    # Branch name, commit sha or pull request number.
    external_id = models.CharField(max_length=255)
    title = models.TextField(blank=True, default="")
    url = models.TextField(blank=True, default="")
    # open | draft | merged | closed (pull requests), open | deleted (branches)
    state = models.CharField(max_length=30, blank=True, default="")
    author_login = models.CharField(max_length=255, blank=True, default="")
    author_name = models.CharField(max_length=255, blank=True, default="")
    author_avatar_url = models.TextField(blank=True, default="")
    event_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        verbose_name = "IssueDevelopmentLink"
        verbose_name_plural = "IssueDevelopmentLinks"
        db_table = "issue_development_links"
        ordering = ("-event_at", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "provider", "kind", "repository", "external_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="issue_development_link_unique_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.kind} {self.repository}@{self.external_id}"


class ProjectGitHubSettings(ProjectBaseModel):
    """Per-project behaviour of the GitHub integration (smart commits and automations)."""

    smart_commits = models.BooleanField(default=True)
    pr_opened_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    pr_merged_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "ProjectGitHubSettings"
        verbose_name_plural = "ProjectGitHubSettings"
        db_table = "project_github_settings"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="project_github_settings_unique_project_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"GitHub <{self.project.name}>"
