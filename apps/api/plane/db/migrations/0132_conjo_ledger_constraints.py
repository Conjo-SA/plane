# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models
from django.db.models import Count


def drop_duplicate_credits(apps, schema_editor):
    """Keep the oldest credit of each month when a concurrent refresh created two (none consumed)."""
    HourLedgerEntry = apps.get_model("db", "HourLedgerEntry")
    duplicated = (
        HourLedgerEntry.objects.filter(kind="credit", deleted_at__isnull=True)
        .values("contract_id", "period")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    for row in duplicated:
        credits = list(
            HourLedgerEntry.objects.filter(
                kind="credit", deleted_at__isnull=True, contract_id=row["contract_id"], period=row["period"]
            ).order_by("created_at")
        )
        for extra in credits[1:]:
            extra.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0131_conjo_billing"),
    ]

    operations = [
        migrations.RunPython(drop_duplicate_credits, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="hourledgerentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True), ("kind", "credit")),
                fields=("contract", "period"),
                name="conjo_hour_ledger_one_credit_per_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="hourledgerentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True), ("reversed_entry__isnull", False)),
                fields=("reversed_entry",),
                name="conjo_hour_ledger_one_reversal_per_debit",
            ),
        ),
    ]
