# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models

# Module imports
from .project import ProjectBaseModel


class ProjectChatIntegration(ProjectBaseModel):
    """Links a project to a Conjo Chat (Matrix) room that receives work item notices."""

    enabled = models.BooleanField(default=False)
    room_id = models.CharField(max_length=255, null=True, blank=True)
    room_name = models.CharField(max_length=255, null=True, blank=True)
    notify_issue_created = models.BooleanField(default=True)
    notify_state_changed = models.BooleanField(default=True)
    notify_assignee_changed = models.BooleanField(default=True)
    notify_comment_created = models.BooleanField(default=True)
    # Pull requests opened/merged on GitHub that mention a work item.
    notify_github = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ProjectChatIntegration"
        verbose_name_plural = "ProjectChatIntegrations"
        db_table = "project_chat_integrations"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="project_chat_integration_unique_project_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.room_id or '-'} <{self.project.name}>"
