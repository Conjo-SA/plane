# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0129_projectchatintegration"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectchatintegration",
            name="notify_github",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="IssueDevelopmentLink",
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
                ("provider", models.CharField(default="github", max_length=30)),
                (
                    "kind",
                    models.CharField(
                        choices=[("branch", "Branch"), ("commit", "Commit"), ("pull_request", "Pull request")],
                        max_length=30,
                    ),
                ),
                ("repository", models.CharField(max_length=255)),
                ("external_id", models.CharField(max_length=255)),
                ("title", models.TextField(blank=True, default="")),
                ("url", models.TextField(blank=True, default="")),
                ("state", models.CharField(blank=True, default="", max_length=30)),
                ("author_login", models.CharField(blank=True, default="", max_length=255)),
                ("author_name", models.CharField(blank=True, default="", max_length=255)),
                ("author_avatar_url", models.TextField(blank=True, default="")),
                ("event_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(default=dict)),
                (
                    "issue",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="development_links",
                        to="db.issue",
                    ),
                ),
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
                "verbose_name": "IssueDevelopmentLink",
                "verbose_name_plural": "IssueDevelopmentLinks",
                "db_table": "issue_development_links",
                "ordering": ("-event_at", "-created_at"),
            },
        ),
        migrations.AddConstraint(
            model_name="issuedevelopmentlink",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("issue", "provider", "kind", "repository", "external_id"),
                name="issue_development_link_unique_when_deleted_at_null",
            ),
        ),
        migrations.CreateModel(
            name="ProjectGitHubSettings",
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
                ("smart_commits", models.BooleanField(default=True)),
                (
                    "pr_opened_state",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="db.state",
                    ),
                ),
                (
                    "pr_merged_state",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="db.state",
                    ),
                ),
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
                "verbose_name": "ProjectGitHubSettings",
                "verbose_name_plural": "ProjectGitHubSettings",
                "db_table": "project_github_settings",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="projectgithubsettings",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("project",),
                name="project_github_settings_unique_project_when_deleted_at_null",
            ),
        ),
    ]
