# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass
class MCPTool:
    """A single MCP tool: JSON-schema definition plus the handler callable."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]
    category: str = "general"

    def to_mcp_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# Global registry of every tool the MCP server can expose
TOOL_REGISTRY: Dict[str, MCPTool] = {}


def register_tool(name: str, description: str, input_schema: Dict[str, Any], category: str = "general"):
    """Decorator that registers a handler function as an MCP tool."""

    def decorator(func: Callable[..., Any]):
        TOOL_REGISTRY[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=func,
            category=category,
        )
        return func

    return decorator
