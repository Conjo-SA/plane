# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: who enters each area of the workspace (MAN-467).

- ``WorkspaceAreaAccess``: which workspace roles (Member, Guest) enter an area. Without a row, the area keeps
  its default (see ``plane.utils.conjo_areas.DEFAULT_ROLES``). Workspace admins always enter.
- ``WorkspaceAreaMemberOverride``: lets one person in (``allow=True``) or keeps them out (``allow=False``),
  above their role. It never keeps an admin out.

The area is an extra gate: it never grants what the role does not already allow.
"""

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .base import BaseModel

AREA_CHOICES = (
    ("clients", "Clientes"),
    ("docs", "Documentação"),
    ("time", "Horas e orçamento"),
    ("integrations", "Integrações"),
    ("archives", "Arquivos"),
)


class WorkspaceAreaAccess(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    area = models.CharField(max_length=32, choices=AREA_CHOICES)
    # Workspace roles that enter the area besides the admin: 15 (Member) and/or 5 (Guest).
    allowed_roles = models.JSONField(default=list)

    class Meta:
        verbose_name = "WorkspaceAreaAccess"
        verbose_name_plural = "WorkspaceAreaAccesses"
        db_table = "conjo_workspace_area_access"
        ordering = ("area",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "area"],
                condition=models.Q(deleted_at__isnull=True),
                name="conjo_area_access_unique_workspace_area",
            )
        ]

    def __str__(self):
        return f"{self.area} {self.allowed_roles} <{self.workspace_id}>"


class WorkspaceAreaMemberOverride(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    area = models.CharField(max_length=32, choices=AREA_CHOICES)
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    allow = models.BooleanField()

    class Meta:
        verbose_name = "WorkspaceAreaMemberOverride"
        verbose_name_plural = "WorkspaceAreaMemberOverrides"
        db_table = "conjo_workspace_area_member_overrides"
        ordering = ("area", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "area", "member"],
                condition=models.Q(deleted_at__isnull=True),
                name="conjo_area_override_unique_workspace_area_member",
            )
        ]

    def __str__(self):
        return f"{self.area} {'liberado' if self.allow else 'bloqueado'} <{self.member_id}>"
