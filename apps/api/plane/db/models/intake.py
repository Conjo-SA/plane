# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from uuid import uuid4

# Django imports
from django.db import models

# Module imports
from plane.db.models.project import ProjectBaseModel
from plane.db.models.workspace import WorkspaceBaseModel


def get_intake_portal_anchor():
    return uuid4().hex


class Intake(ProjectBaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(verbose_name="Intake Description", blank=True)
    is_default = models.BooleanField(default=False)
    view_props = models.JSONField(default=dict)
    logo_props = models.JSONField(default=dict)

    def __str__(self):
        """Return name of the intake"""
        return f"{self.name} <{self.project.name}>"

    class Meta:
        unique_together = ["name", "project", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "project"],
                condition=models.Q(deleted_at__isnull=True),
                name="intake_unique_name_project_when_deleted_at_null",
            )
        ]
        verbose_name = "Intake"
        verbose_name_plural = "Intakes"
        db_table = "intakes"
        ordering = ("name",)


class SourceType(models.TextChoices):
    IN_APP = "IN_APP"
    PORTAL = "PORTAL"


class IntakeIssueStatus(models.IntegerChoices):
    PENDING = -2
    REJECTED = -1
    SNOOZED = 0
    ACCEPTED = 1
    DUPLICATE = 2


class IntakeIssue(ProjectBaseModel):
    intake = models.ForeignKey("db.Intake", related_name="issue_intake", on_delete=models.CASCADE)
    issue = models.ForeignKey("db.Issue", related_name="issue_intake", on_delete=models.CASCADE)
    status = models.IntegerField(
        choices=(
            (-2, "Pending"),
            (-1, "Rejected"),
            (0, "Snoozed"),
            (1, "Accepted"),
            (2, "Duplicate"),
        ),
        default=-2,
    )
    snoozed_till = models.DateTimeField(null=True)
    duplicate_to = models.ForeignKey(
        "db.Issue",
        related_name="intake_duplicate",
        on_delete=models.SET_NULL,
        null=True,
    )
    source = models.CharField(max_length=255, default="IN_APP", null=True, blank=True)
    source_email = models.TextField(blank=True, null=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True, null=True)
    extra = models.JSONField(default=dict)

    class Meta:
        verbose_name = "IntakeIssue"
        verbose_name_plural = "IntakeIssues"
        db_table = "intake_issues"
        ordering = ("-created_at",)

    def __str__(self):
        """Return name of the Issue"""
        return f"{self.issue.name} <{self.intake.name}>"


class IntakePortal(ProjectBaseModel):
    """Public request form that lets external requesters submit work items into a project's intake."""

    intake = models.ForeignKey("db.Intake", related_name="portals", on_delete=models.CASCADE)
    anchor = models.CharField(max_length=255, default=get_intake_portal_anchor, unique=True, db_index=True)
    # Human friendly alias for the anchor, so links can be shared as /intake/<slug>
    slug = models.CharField(max_length=60, unique=True, null=True, blank=True, db_index=True)
    is_enabled = models.BooleanField(default=False)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    success_message = models.TextField(blank=True)
    is_attachment_enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = "IntakePortal"
        verbose_name_plural = "IntakePortals"
        db_table = "intake_portals"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="intake_portal_unique_project_when_deleted_at_null",
            )
        ]

    def __str__(self):
        """Return the anchor of the portal"""
        return f"{self.anchor} <{self.project.name}>"


class IntakePortalVerification(WorkspaceBaseModel):
    """One-time code used to prove ownership of a requester email address."""

    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = "IntakePortalVerification"
        verbose_name_plural = "IntakePortalVerifications"
        db_table = "intake_portal_verifications"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.email}"


class IntakePortalSession(WorkspaceBaseModel):
    """Session issued to a requester after a successful email verification."""

    email = models.EmailField(db_index=True)
    token_hash = models.CharField(max_length=255, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "IntakePortalSession"
        verbose_name_plural = "IntakePortalSessions"
        db_table = "intake_portal_sessions"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.email}"


class IntakePortalBudgetStatus(models.TextChoices):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class IntakePortalBudget(ProjectBaseModel):
    """Hourly effort estimate a requester has to approve before the work starts.

    Approval is deliberately one way: once a requester approves an estimate it
    becomes an immutable record, so neither side can silently revoke or reprice
    work that was already agreed on. A rejection is not terminal, so the team can
    send a revised estimate for the same ticket.
    """

    issue = models.OneToOneField("db.Issue", related_name="portal_budget", on_delete=models.CASCADE)
    estimated_hours = models.DecimalField(max_digits=7, decimal_places=2)
    note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=IntakePortalBudgetStatus.choices,
        default=IntakePortalBudgetStatus.PENDING,
    )
    requested_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_email = models.EmailField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by_email = models.EmailField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        verbose_name = "IntakePortalBudget"
        verbose_name_plural = "IntakePortalBudgets"
        db_table = "intake_portal_budgets"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.estimated_hours}h <{self.status}>"
