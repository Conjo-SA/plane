# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import secrets

# Django imports
from django.db import models

# Module imports
from plane.db.models import BaseModel


def generate_mcp_token():
    return "plane_mcp_" + secrets.token_hex(24)


class MCPServer(BaseModel):
    """
    Singleton-style configuration for the instance-level MCP server.

    The server exposes Plane's domain (workspaces, projects, work items,
    cycles, modules, states, labels and pages) over the Model Context
    Protocol so external AI clients can read and write Plane data.
    """

    name = models.CharField(max_length=255, default="Plane MCP Server")
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=False)
    token = models.CharField(
        max_length=255, unique=True, default=generate_mcp_token, db_index=True
    )
    # Names of registry tools that are explicitly disabled. Empty means
    # every registered tool is available.
    disabled_tools = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "MCP Server"
        verbose_name_plural = "MCP Servers"
        db_table = "mcp_servers"
        ordering = ("-created_at",)

    def __str__(self):
        return self.name

    @classmethod
    def get_instance(cls):
        """Return the first (singleton) MCP server config, if any."""
        return cls.objects.first()

    def regenerate_token(self, save=True):
        self.token = generate_mcp_token()
        if save:
            self.save(update_fields=["token", "updated_at"])
        return self.token

    def is_tool_enabled(self, tool_name):
        return tool_name not in (self.disabled_tools or [])


class MCPToolCallLog(BaseModel):
    """Audit trail for every tools/call handled by the MCP server."""

    STATUS_CHOICES = (
        ("success", "Success"),
        ("error", "Error"),
    )

    tool_name = models.CharField(max_length=255, db_index=True)
    arguments = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="success", db_index=True
    )
    error_message = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "MCP Tool Call Log"
        verbose_name_plural = "MCP Tool Call Logs"
        db_table = "mcp_tool_call_logs"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.tool_name} ({self.status})"
