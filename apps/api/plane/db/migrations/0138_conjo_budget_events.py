# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): timeline de cada orçamento (envio, alterações da equipe, resposta do cliente).

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def events_from_existing_budgets(apps, schema_editor):
    Budget = apps.get_model("db", "IntakePortalBudget")
    Event = apps.get_model("db", "IntakePortalBudgetEvent")
    events = []
    for budget in Budget.objects.filter(deleted_at__isnull=True):
        common = {
            "budget_id": budget.id,
            "project_id": budget.project_id,
            "workspace_id": budget.workspace_id,
            "hours": budget.estimated_hours,
            "note": budget.note or "",
        }
        events.append(
            Event(
                kind="sent",
                actor_id=budget.created_by_id,
                occurred_at=budget.requested_at or budget.created_at,
                **common,
            )
        )
        if budget.approved_at:
            events.append(
                Event(
                    kind="approved",
                    actor_email=budget.approved_by_email or "",
                    occurred_at=budget.approved_at,
                    **common,
                )
            )
        if budget.rejected_at:
            events.append(
                Event(
                    kind="rejected",
                    actor_email=budget.rejected_by_email or "",
                    reason=budget.rejection_reason or "",
                    occurred_at=budget.rejected_at,
                    **common,
                )
            )
    Event.objects.bulk_create(events, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("db", "0137_conjo_multiple_budgets"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntakePortalBudgetEvent",
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
                    "kind",
                    models.CharField(
                        choices=[
                            ("sent", "Enviado"),
                            ("revised", "Alterado"),
                            ("approved", "Aprovado"),
                            ("rejected", "Recusado"),
                        ],
                        max_length=20,
                    ),
                ),
                ("hours", models.DecimalField(decimal_places=2, max_digits=7)),
                ("note", models.TextField(blank=True)),
                ("previous_hours", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("previous_note", models.TextField(blank=True)),
                ("actor_email", models.EmailField(blank=True, max_length=254)),
                ("reason", models.TextField(blank=True)),
                ("occurred_at", models.DateTimeField()),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "budget",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="events", to="db.intakeportalbudget"
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
                        on_delete=django.db.models.deletion.CASCADE, related_name="project_%(class)s", to="db.project"
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
                "verbose_name": "IntakePortalBudgetEvent",
                "verbose_name_plural": "IntakePortalBudgetEvents",
                "db_table": "intake_portal_budget_events",
                "ordering": ("occurred_at", "created_at"),
            },
        ),
        migrations.RunPython(events_from_existing_budgets, migrations.RunPython.noop),
    ]
