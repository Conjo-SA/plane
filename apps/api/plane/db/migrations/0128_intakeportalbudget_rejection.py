# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0127_intakeportalbudget"),
    ]

    operations = [
        migrations.AddField(
            model_name="intakeportalbudget",
            name="rejected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="intakeportalbudget",
            name="rejected_by_email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.AddField(
            model_name="intakeportalbudget",
            name="rejection_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="intakeportalbudget",
            name="status",
            field=models.CharField(
                choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")],
                default="PENDING",
                max_length=20,
            ),
        ),
    ]
