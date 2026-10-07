# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): colunas do board em português e o momento em que cada card entrou na coluna atual.

from django.db import migrations, models
from django.template.defaultfilters import slugify

# Nomes em inglês (padrão do Plane) -> nome em português usado nos projetos novos.
STATE_NAMES_PTBR = {
    "todo": "A fazer",
    "to do": "A fazer",
    "in progress": "Em andamento",
    "done": "Concluída",
    "completed": "Concluída",
    "cancelled": "Cancelada",
    "canceled": "Cancelada",
    "triage": "Triagem",
    "intake": "Triagem",
    "waiting": "Aguardando",
    "blocked": "Bloqueada",
    "in review": "Em revisão",
    "review": "Em revisão",
}


def rename_states(apps, schema_editor):
    State = apps.get_model("db", "State")
    for state in State.objects.filter(deleted_at__isnull=True).only("id", "name", "project_id"):
        target = STATE_NAMES_PTBR.get(state.name.strip().lower())
        if not target or target == state.name:
            continue
        # O nome é único por projeto: se o projeto já tem a coluna em português, deixa como está.
        taken = (
            State.objects.filter(project_id=state.project_id, name=target, deleted_at__isnull=True)
            .exclude(pk=state.pk)
            .exists()
        )
        if taken:
            continue
        State.objects.filter(pk=state.pk).update(name=target, slug=slugify(target))


def backfill_state_changed_at(apps, schema_editor):
    # Última troca de estado registrada no histórico; sem troca, o card está na coluna desde que foi criado.
    schema_editor.execute(
        """
        UPDATE issues AS i
        SET state_changed_at = COALESCE(
            (
                SELECT MAX(a.created_at)
                FROM issue_activities AS a
                WHERE a.issue_id = i.id AND a.field = 'state' AND a.deleted_at IS NULL
            ),
            i.created_at
        )
        WHERE i.state_changed_at IS NULL
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0135_conjo_default_language_ptbr"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="state_changed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(rename_states, migrations.RunPython.noop),
        migrations.RunPython(backfill_state_changed_at, migrations.RunPython.noop),
    ]
