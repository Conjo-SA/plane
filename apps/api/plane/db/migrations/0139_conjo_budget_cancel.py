# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): a equipe pode cancelar um orçamento pendente ou recusado (MAN-156).
# Só adiciona colunas que aceitam vazio e opções novas (CANCELLED / cancelled): reversível e sem tocar nos dados.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("db", "0138_conjo_budget_events"),
    ]

    operations = [
        migrations.AddField(
            model_name="intakeportalbudget",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="intakeportalbudget",
            name="cancelled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="intakeportalbudget",
            name="cancellation_reason",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="intakeportalbudget",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="intakeportalbudgetevent",
            name="kind",
            field=models.CharField(
                choices=[
                    ("sent", "Enviado"),
                    ("revised", "Alterado"),
                    ("approved", "Aprovado"),
                    ("rejected", "Recusado"),
                    ("cancelled", "Cancelado"),
                ],
                max_length=20,
            ),
        ),
    ]
