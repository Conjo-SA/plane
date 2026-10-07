# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: time tracking, clients (CRM), hour packages and their ledger.

- ``IssueWorkLog``: time spent on a work item.
- ``IssueWorkKind``: whether a work item is an evolution (debits the client's package), maintenance
  or internal work (counted, never debited).
- ``Client`` / ``ClientContact`` / ``ClientProject`` / ``ClientLabel``: who the work is for (a whole
  project, or a label on a board shared by several clients).
- ``ClientContract``: a monthly hour package; each monthly credit is valid for ``accumulation_months``.
- ``HourLedgerEntry``: the package statement (credits, debits, expirations, reversals, adjustments and
  excess hours). Credits are lots: debits consume the lot that expires first.
- ``ClientTimelineNote``: meetings, calls, e-mails and notes on the client's timeline.
"""

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .base import BaseModel
from .project import ProjectBaseModel


class IssueWorkLog(ProjectBaseModel):
    SOURCE_MANUAL = "manual"
    SOURCE_COMMIT = "commit"
    SOURCE_CHAT = "chat"
    SOURCE_CHOICES = ((SOURCE_MANUAL, "Manual"), (SOURCE_COMMIT, "Commit"), (SOURCE_CHAT, "Chat"))

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="work_logs")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="work_logs")
    minutes = models.PositiveIntegerField()
    logged_on = models.DateField()
    description = models.TextField(blank=True, default="")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    # Commit sha (or chat event id) so the same source is never logged twice.
    external_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "IssueWorkLog"
        verbose_name_plural = "IssueWorkLogs"
        db_table = "issue_work_logs"
        ordering = ("-logged_on", "-created_at")

    def __str__(self):
        return f"{self.minutes}min <{self.issue_id}>"


class IssueWorkKind(ProjectBaseModel):
    EVOLUTION = "evolution"
    MAINTENANCE = "maintenance"
    INTERNAL = "internal"
    KIND_CHOICES = ((EVOLUTION, "Evolução"), (MAINTENANCE, "Manutenção"), (INTERNAL, "Interno"))

    issue = models.OneToOneField("db.Issue", on_delete=models.CASCADE, related_name="work_kind")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)

    class Meta:
        verbose_name = "IssueWorkKind"
        verbose_name_plural = "IssueWorkKinds"
        db_table = "issue_work_kinds"

    def __str__(self):
        return f"{self.kind} <{self.issue_id}>"


class ClientBaseModel(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True


class Client(ClientBaseModel):
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True, default="")
    document = models.CharField(max_length=32, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        db_table = "conjo_clients"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ClientContact(ClientBaseModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    role = models.CharField(max_length=128, blank=True, default="")
    can_approve = models.BooleanField(default=False)

    class Meta:
        verbose_name = "ClientContact"
        verbose_name_plural = "ClientContacts"
        db_table = "conjo_client_contacts"
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} <{self.client_id}>"


class ClientProject(ClientBaseModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_projects")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = "ClientProject"
        verbose_name_plural = "ClientProjects"
        db_table = "conjo_client_projects"
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="conjo_client_project_unique_project",
            )
        ]

    def __str__(self):
        return f"{self.project_id} <{self.client_id}>"


class ClientLabel(ClientBaseModel):
    """The label used for the client on a board (e.g. "RastroPOP" on MAN), kept in sync with the card's client.

    Choosing the client on a card applies the label; a portal link with the label's tag sets the client;
    adding the label to a card without a client sets it.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_labels")
    label = models.ForeignKey("db.Label", on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = "ClientLabel"
        verbose_name_plural = "ClientLabels"
        db_table = "conjo_client_labels"
        constraints = [
            models.UniqueConstraint(
                fields=["label"],
                condition=models.Q(deleted_at__isnull=True),
                name="conjo_client_label_unique_label",
            )
        ]

    def __str__(self):
        return f"{self.label_id} <{self.client_id}>"


class IssueClient(ProjectBaseModel):
    """The client a work item is for, chosen on the item (boards shared by several clients, like MAN).

    Without it, the work item belongs to the client of its project (projects dedicated to one client).
    """

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="conjo_clients")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="issue_links")

    class Meta:
        verbose_name = "IssueClient"
        verbose_name_plural = "IssueClients"
        db_table = "conjo_issue_clients"
        constraints = [
            # One client per work item; soft-deleted rows (a cleared client) do not count.
            models.UniqueConstraint(
                fields=["issue"],
                condition=models.Q(deleted_at__isnull=True),
                name="conjo_issue_client_unique_issue",
            )
        ]

    def __str__(self):
        return f"{self.client_id} <{self.issue_id}>"


class ClientContract(ClientBaseModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contracts")
    name = models.CharField(max_length=255)
    hours_per_month = models.DecimalField(max_digits=7, decimal_places=2)
    # How many months a monthly credit stays usable (1 = no accumulation, 12 = the whole year).
    accumulation_months = models.PositiveSmallIntegerField(default=3)
    credit_day = models.PositiveSmallIntegerField(default=1)
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    low_balance_percent = models.PositiveSmallIntegerField(default=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ClientContract"
        verbose_name_plural = "ClientContracts"
        db_table = "conjo_client_contracts"
        ordering = ("-starts_on",)

    def __str__(self):
        return f"{self.name} <{self.client_id}>"


class HourLedgerEntry(ClientBaseModel):
    CREDIT = "credit"
    DEBIT = "debit"
    EXPIRATION = "expiration"
    REVERSAL = "reversal"
    ADJUSTMENT = "adjustment"
    EXCESS = "excess"
    KIND_CHOICES = (
        (CREDIT, "Crédito"),
        (DEBIT, "Débito"),
        (EXPIRATION, "Expiração"),
        (REVERSAL, "Estorno"),
        (ADJUSTMENT, "Ajuste"),
        (EXCESS, "Excedente"),
    )

    contract = models.ForeignKey(ClientContract, on_delete=models.CASCADE, related_name="ledger")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    # Effect on the balance: positive for credits, reversals and positive adjustments; negative for
    # debits, expirations and negative adjustments; excess hours are informational (0 effect).
    hours = models.DecimalField(max_digits=8, decimal_places=2)
    occurred_on = models.DateField()
    issue = models.ForeignKey("db.Issue", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.TextField(blank=True, default="")
    # Lots (credits, positive adjustments and reversals of expired lots open no lot).
    period = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    remaining = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    # Debits: [{"lot": "<entry id>", "hours": "8.00"}] so a reversal can give hours back to their lots.
    allocations = models.JSONField(default=list, blank=True)
    reversed_entry = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reversals"
    )
    approved_by_email = models.EmailField(blank=True, default="")
    exported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "HourLedgerEntry"
        verbose_name_plural = "HourLedgerEntries"
        db_table = "conjo_hour_ledger"
        ordering = ("-occurred_on", "-created_at")
        constraints = [
            # Last line of defence against concurrent refreshes: one monthly credit per period.
            models.UniqueConstraint(
                fields=["contract", "period"],
                condition=models.Q(kind="credit", deleted_at__isnull=True),
                name="conjo_hour_ledger_one_credit_per_period",
            ),
            # A debit is reversed at most once.
            models.UniqueConstraint(
                fields=["reversed_entry"],
                condition=models.Q(reversed_entry__isnull=False, deleted_at__isnull=True),
                name="conjo_hour_ledger_one_reversal_per_debit",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.hours}h <{self.contract_id}>"


class ClientTimelineNote(ClientBaseModel):
    MEETING = "meeting"
    CALL = "call"
    EMAIL = "email"
    NOTE = "note"
    KIND_CHOICES = ((MEETING, "Reunião"), (CALL, "Ligação"), (EMAIL, "E-mail"), (NOTE, "Nota"))

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="timeline_notes")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=NOTE)
    occurred_at = models.DateTimeField()
    body = models.TextField()
    contact_ids = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "ClientTimelineNote"
        verbose_name_plural = "ClientTimelineNotes"
        db_table = "conjo_client_timeline_notes"
        ordering = ("-occurred_at",)

    def __str__(self):
        return f"{self.kind} <{self.client_id}>"
