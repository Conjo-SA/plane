# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models

# Module imports
from plane.db.models.project import ProjectBaseModel

# Marker stored on the checklist sub-issues so the gate can tell which children it
# owns (and ignore unrelated sub-issues the team may have added by hand).
DEPLOY_CHECKLIST_SOURCE = "deploy-checklist"

# Default company-wide deploy checklist. Editable per project via the `items` field.
DEFAULT_DEPLOY_CHECKLIST_ITEMS = [
    "Teste em homologação com prova (comentário no ticket)",
    "Conferência das ENVs, se houver",
    "Build concluído com prova",
    "Indicação de que a alteração subiu em PROD com prova",
]


def get_default_deploy_checklist_items():
    return list(DEFAULT_DEPLOY_CHECKLIST_ITEMS)


class DeployChecklistTemplate(ProjectBaseModel):
    """Opt-in, per-project deploy checklist.

    When a project has an enabled template, a work item cannot enter the Completed
    state group (its move to "Concluída"/production is reverted) until every checklist
    sub-issue is completed. Projects without a template are unaffected.
    """

    is_enabled = models.BooleanField(default=True)
    items = models.JSONField(default=get_default_deploy_checklist_items)

    class Meta:
        verbose_name = "DeployChecklistTemplate"
        verbose_name_plural = "DeployChecklistTemplates"
        db_table = "deploy_checklist_templates"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="deploy_checklist_unique_project_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"DeployChecklistTemplate <{self.project_id}>"
