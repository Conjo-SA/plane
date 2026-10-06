# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0128_intakeportalbudget_rejection"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectChatIntegration",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created At")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Last Modified At")),
                ("deleted_at", models.DateTimeField(blank=True, null=True, verbose_name="Deleted At")),
                (
                    "id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("room_id", models.CharField(blank=True, max_length=255, null=True)),
                ("room_name", models.CharField(blank=True, max_length=255, null=True)),
                ("notify_issue_created", models.BooleanField(default=True)),
                ("notify_state_changed", models.BooleanField(default=True)),
                ("notify_assignee_changed", models.BooleanField(default=True)),
                ("notify_comment_created", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_%(class)s",
                        to="db.project",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_updated_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last Modified By",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_%(class)s",
                        to="db.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "ProjectChatIntegration",
                "verbose_name_plural": "ProjectChatIntegrations",
                "db_table": "project_chat_integrations",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="projectchatintegration",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("project",),
                name="project_chat_integration_unique_project_when_deleted_at_null",
            ),
        ),
    ]
