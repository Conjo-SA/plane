# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): relatório do mês anterior por e-mail no primeiro dia útil (CONJO-52).
# Só adiciona colunas com padrão desligado e uma tabela nova: reversível e sem tocar nos dados.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("db", "0139_conjo_budget_cancel"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="monthly_report_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="clientcontact",
            name="receives_report",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="ClientReportDelivery",
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
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("number", models.CharField(blank=True, default="", max_length=64)),
                (
                    "trigger",
                    models.CharField(choices=[("auto", "Mensal"), ("manual", "Manual")], default="auto", max_length=10),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Na fila"),
                            ("sending", "Enviando"),
                            ("sent", "Enviado"),
                            ("failed", "Falhou"),
                            ("skipped", "Não enviado"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("recipients", models.JSONField(blank=True, default=list)),
                ("delivered_to", models.JSONField(blank=True, default=list)),
                ("test_mode", models.BooleanField(default=False)),
                ("reason", models.TextField(blank=True, default="")),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report_deliveries",
                        to="db.client",
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
                "verbose_name": "ClientReportDelivery",
                "verbose_name_plural": "ClientReportDeliveries",
                "db_table": "conjo_client_report_deliveries",
                "ordering": ("-created_at",),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("deleted_at__isnull", True), ("trigger", "auto")),
                        fields=("client", "period_start", "period_end"),
                        name="conjo_report_delivery_unique_auto",
                    )
                ],
            },
        ),
    ]
