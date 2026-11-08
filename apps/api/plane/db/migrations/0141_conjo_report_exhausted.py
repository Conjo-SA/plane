# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): relatório no dia em que o pacote de horas esgota (CONJO-52).
# Só acrescenta uma opção e uma restrição sobre linhas que ainda não existem: reversível e sem tocar nos dados.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0140_conjo_report_delivery"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clientreportdelivery",
            name="trigger",
            field=models.CharField(
                choices=[("auto", "Mensal"), ("manual", "Manual"), ("exhausted", "Pacote esgotado")],
                default="auto",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="clientreportdelivery",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True), ("trigger", "exhausted")),
                fields=("client", "period_start", "period_end"),
                name="conjo_report_delivery_unique_exhausted",
            ),
        ),
    ]
