# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): vários orçamentos por chamado (um pendente por vez) e o débito ligado ao orçamento.

import django.db.models.deletion
from django.db import migrations, models


def link_ledger_to_budgets(apps, schema_editor):
    # Até aqui cada chamado tinha no máximo um orçamento: débitos e excedentes do chamado são dele.
    schema_editor.execute(
        """
        UPDATE conjo_hour_ledger AS l
        SET budget_id = b.id
        FROM intake_portal_budgets AS b
        WHERE l.issue_id = b.issue_id
          AND l.budget_id IS NULL
          AND l.kind IN ('debit', 'excess')
          AND b.deleted_at IS NULL
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0136_conjo_states_ptbr_state_changed_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="intakeportalbudget",
            name="issue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="portal_budgets", to="db.issue"
            ),
        ),
        migrations.AddConstraint(
            model_name="intakeportalbudget",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True), ("status", "PENDING")),
                fields=("issue",),
                name="intake_portal_budget_one_pending_per_issue",
            ),
        ),
        migrations.AddField(
            model_name="hourledgerentry",
            name="budget",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ledger_entries",
                to="db.intakeportalbudget",
            ),
        ),
        migrations.RunPython(link_ledger_to_budgets, migrations.RunPython.noop),
    ]
