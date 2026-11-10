# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): permissão por área do workspace (MAN-467).
# Só cria duas tabelas novas, sem tocar nos dados existentes: reversível. Sem linha salva, cada área usa o
# padrão do código (Clientes só para administradores; as demais com o acesso de antes).

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0141_conjo_report_exhausted"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceAreaAccess",
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
                (
                    "area",
                    models.CharField(
                        choices=[
                            ("clients", "Clientes"),
                            ("docs", "Documentação"),
                            ("time", "Horas e orçamento"),
                            ("integrations", "Integrações"),
                            ("archives", "Arquivos"),
                        ],
                        max_length=32,
                    ),
                ),
                ("allowed_roles", models.JSONField(default=list)),
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
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="db.workspace"),
                ),
            ],
            options={
                "verbose_name": "WorkspaceAreaAccess",
                "verbose_name_plural": "WorkspaceAreaAccesses",
                "db_table": "conjo_workspace_area_access",
                "ordering": ("area",),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("deleted_at__isnull", True)),
                        fields=("workspace", "area"),
                        name="conjo_area_access_unique_workspace_area",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceAreaMemberOverride",
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
                (
                    "area",
                    models.CharField(
                        choices=[
                            ("clients", "Clientes"),
                            ("docs", "Documentação"),
                            ("time", "Horas e orçamento"),
                            ("integrations", "Integrações"),
                            ("archives", "Arquivos"),
                        ],
                        max_length=32,
                    ),
                ),
                ("allow", models.BooleanField()),
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
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL
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
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="db.workspace"),
                ),
            ],
            options={
                "verbose_name": "WorkspaceAreaMemberOverride",
                "verbose_name_plural": "WorkspaceAreaMemberOverrides",
                "db_table": "conjo_workspace_area_member_overrides",
                "ordering": ("area", "created_at"),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("deleted_at__isnull", True)),
                        fields=("workspace", "area", "member"),
                        name="conjo_area_override_unique_workspace_area_member",
                    )
                ],
            },
        ),
    ]
