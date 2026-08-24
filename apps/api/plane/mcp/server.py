# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Minimal Model Context Protocol server (JSON-RPC 2.0 over HTTP POST).

Implements the subset of the protocol needed by MCP clients:
`initialize`, `ping`, `notifications/*`, `tools/list` and `tools/call`.
"""

# Python imports
import json
import time

# Module imports
from plane.mcp.models import MCPServer, MCPToolCallLog
from plane.mcp.tools import TOOL_REGISTRY
from plane.mcp.tools.handlers import MCPToolError
from plane.utils.exception_logger import log_exception

# MCP protocol revision this server speaks
PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {
    "name": "plane-mcp",
    "title": "Plane MCP Server",
    "version": "1.0.0",
}

SERVER_INSTRUCTIONS = (
    "Plane MCP server. Use the workspace_slug (e.g. 'my-company') to scope every call. "
    "Projects accept either their UUID or their short identifier (e.g. 'PLANE') and work "
    "items accept either their UUID or their human identifier (e.g. 'PLANE-123')."
)

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class MCPProtocolError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _enabled_tools(server: MCPServer):
    return [
        tool
        for tool in sorted(TOOL_REGISTRY.values(), key=lambda tool: tool.name)
        if server.is_tool_enabled(tool.name)
    ]


def _handle_initialize(request_id, params):
    return _result(
        request_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": SERVER_INSTRUCTIONS,
        },
    )


def _handle_tools_list(request_id, server):
    return _result(
        request_id,
        {"tools": [tool.to_mcp_definition() for tool in _enabled_tools(server)]},
    )


def _handle_tools_call(request_id, params, server):
    if not isinstance(params, dict):
        raise MCPProtocolError(INVALID_PARAMS, "tools/call params must be an object")

    tool_name = params.get("name")
    arguments = params.get("arguments") or {}

    if not tool_name or not isinstance(tool_name, str):
        raise MCPProtocolError(INVALID_PARAMS, "tools/call requires a 'name' string param")
    if not isinstance(arguments, dict):
        raise MCPProtocolError(INVALID_PARAMS, "tools/call 'arguments' must be an object")

    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None or not server.is_tool_enabled(tool_name):
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": f"Unknown or disabled tool: {tool_name}"}],
                "isError": True,
            },
        )

    started_at = time.monotonic()
    try:
        output = tool.handler(**arguments)
        payload = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(output, indent=2, default=str),
                }
            ],
            "isError": False,
        }
        _log_tool_call(server, tool_name, arguments, "success", "", started_at)
        return _result(request_id, payload)
    except MCPToolError as exc:
        _log_tool_call(server, tool_name, arguments, "error", str(exc), started_at)
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        )
    except TypeError as exc:
        # Usually a signature mismatch on the provided arguments
        message = f"Invalid arguments for tool '{tool_name}': {exc}"
        _log_tool_call(server, tool_name, arguments, "error", message, started_at)
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": message}],
                "isError": True,
            },
        )
    except Exception as exc:
        log_exception(exc)
        _log_tool_call(server, tool_name, arguments, "error", "Internal error", started_at)
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": "Internal error while running the tool"}],
                "isError": True,
            },
        )


def _log_tool_call(server, tool_name, arguments, status, error_message, started_at):
    try:
        MCPToolCallLog.objects.create(
            tool_name=tool_name,
            arguments=arguments if isinstance(arguments, dict) else {},
            status=status,
            error_message=error_message or "",
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
    except Exception as exc:
        log_exception(exc)


def handle_mcp_message(message, server: MCPServer):
    """Handle a single JSON-RPC message.

    Returns a JSON-RPC response dict, or None for notifications.
    """
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise MCPProtocolError(INVALID_REQUEST, "Payload must be a JSON-RPC 2.0 object")

    method = message.get("method")
    request_id = message.get("id")

    if not isinstance(method, str):
        raise MCPProtocolError(INVALID_REQUEST, "Missing or invalid 'method'")

    # Client notifications never receive a response
    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        return _handle_initialize(request_id, message.get("params") or {})
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _handle_tools_list(request_id, server)
    if method == "tools/call":
        return _handle_tools_call(request_id, message.get("params"), server)

    raise MCPProtocolError(METHOD_NOT_FOUND, f"Method not found: {method}")


def handle_mcp_payload(payload, server: MCPServer):
    """Handle a JSON-RPC payload (single message or batch).

    Returns `(response, status_code)` where response is None when every
    message was a notification (HTTP 202 semantics).
    """
    is_batch = isinstance(payload, list)
    messages = payload if is_batch else [payload]

    if is_batch and not messages:
        return _error(None, INVALID_REQUEST, "Batch must not be empty"), 200

    responses = []
    for message in messages:
        try:
            response = handle_mcp_message(message, server)
        except MCPProtocolError as exc:
            response = _error(message.get("id") if isinstance(message, dict) else None, exc.code, exc.message)
        except Exception as exc:
            log_exception(exc)
            response = _error(
                message.get("id") if isinstance(message, dict) else None,
                INTERNAL_ERROR,
                "Internal error",
            )
        if response is not None:
            responses.append(response)

    if not responses:
        return None, 202

    return (responses if is_batch else responses[0]), 200
