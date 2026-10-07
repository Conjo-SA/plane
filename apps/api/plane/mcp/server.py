# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Minimal Model Context Protocol server (JSON-RPC 2.0 over HTTP POST).

Implements the subset of the protocol needed by MCP clients:
`initialize`, `ping`, `notifications/*`, `tools/list` and `tools/call`.
"""

# Python imports
import json
import math
import re
import time

# Django imports
from django.core.exceptions import ValidationError
from django.db import DataError

# Module imports
from plane.mcp.models import MCPServer, MCPToolCallLog
from plane.mcp.tools import TOOL_REGISTRY
from plane.mcp.tools.handlers import MCPToolError
from plane.utils.exception_logger import log_exception

# MCP protocol revision this server speaks
PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {
    "name": "plane-mcp",
    "title": "Tasks MCP Server",
    "version": "1.1.0",
}

SERVER_INSTRUCTIONS = (
    "Servidor MCP do Tasks. Informe workspace_slug (ex.: 'conjo') em toda chamada. Projetos aceitam o UUID ou o "
    "identificador curto (ex.: 'MAN'); itens de trabalho aceitam o UUID ou o identificador (ex.: 'MAN-123'). "
    "Board: list_states/list_labels/list_cycles/list_modules devolvem os UUIDs que as outras ferramentas usam; "
    "list_work_items filtra por estado, grupo de estado, etiqueta, ciclo, módulo, responsável (UUID ou e-mail), "
    "prazo (due_before, overdue) e cliente; bulk_update_work_items altera vários itens de uma vez. Pedidos novos "
    "esperam na Entrada (list_intake_items, triage_intake_item) antes de ir para o board. "
    "Comentários são internos por padrão; public=true deixa o comentário visível ao cliente no portal. "
    "Clientes e horas: clientes aceitam UUID, nome ou CNPJ/CPF. Lançamentos de horas exigem a pessoa que fez o "
    "trabalho (e-mail do membro). Só itens 'evolution' debitam o pacote de horas do cliente quando o orçamento é "
    "aprovado; 'maintenance' e 'internal' são contados mas nunca debitados. "
    "Ferramentas irreversíveis pedem confirm=true. Toda escrita fica no histórico como 'Assistente (MCP)'. "
    "server_info mostra o que este token pode fazer e os limites."
)

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# A JSON-RPC batch is one HTTP request for the throttle: keep it small so it cannot multiply the rate limit.
MAX_BATCH_SIZE = 20
# Strings without an explicit maxLength in the schema; HTML and long texts declare their own.
DEFAULT_MAX_STRING_LENGTH = 10_000
DEFAULT_MAX_ARRAY_ITEMS = 200

# Audit log: the arguments are kept for the admin, but never whole documents nor secrets.
AUDIT_MAX_STRING = 2048
AUDIT_MAX_ITEMS = 50
AUDIT_MAX_DEPTH = 4
_SECRET_KEY_PATTERN = re.compile(r"(token|secret|password|senha|api[_-]?key|authorization)", re.IGNORECASE)

_TYPE_LABELS = {
    "string": "um texto",
    "integer": "um número inteiro",
    "number": "um número",
    "boolean": "true ou false",
    "array": "uma lista",
    "object": "um objeto",
}


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


def _tool_error(request_id, message):
    return _result(request_id, {"content": [{"type": "text", "text": message}], "isError": True})


def _enabled_tools(server: MCPServer):
    return [
        tool for tool in sorted(TOOL_REGISTRY.values(), key=lambda tool: tool.name) if server.is_tool_enabled(tool.name)
    ]


# ---------------------------------------------------------------------------
# Arguments: checked against the tool's JSON schema before the handler runs
# ---------------------------------------------------------------------------


def _matches_type(value, expected):
    if isinstance(expected, list):
        return any(_matches_type(value, option) for option in expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _check_value(name, value, spec):
    expected = spec.get("type")
    if expected and not _matches_type(value, expected):
        options = expected if isinstance(expected, list) else [expected]
        raise MCPToolError(f"'{name}' deve ser {' ou '.join(_TYPE_LABELS.get(t, t) for t in options)}")
    if "enum" in spec and value not in spec["enum"]:
        raise MCPToolError(f"'{name}' deve ser um destes valores: {', '.join(str(v) for v in spec['enum'])}")
    if isinstance(value, str) and len(value) > spec.get("maxLength", DEFAULT_MAX_STRING_LENGTH):
        raise MCPToolError(f"'{name}' passa do limite de {spec.get('maxLength', DEFAULT_MAX_STRING_LENGTH)} caracteres")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            raise MCPToolError(f"'{name}' deve ser no mínimo {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise MCPToolError(f"'{name}' deve ser no máximo {spec['maximum']}")
    if isinstance(value, list):
        max_items = spec.get("maxItems", DEFAULT_MAX_ARRAY_ITEMS)
        if len(value) > max_items:
            raise MCPToolError(f"'{name}' aceita no máximo {max_items} itens")
        item_spec = spec.get("items") or {}
        for item in value:
            _check_value(f"{name}[]", item, item_spec)


def validate_arguments(schema, arguments):
    """Validate (and normalize) tool arguments against the tool's input schema.

    `null` counts as "not informed", so optional parameters can be sent as null. Unknown parameters,
    wrong types, values outside the enum and oversized strings/lists are refused with a clear message
    instead of reaching the handler.
    """
    arguments = {key: value for key, value in arguments.items() if value is not None}
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise MCPToolError(f"Parâmetro(s) desconhecido(s): {', '.join(unknown)}")
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise MCPToolError(f"Parâmetro(s) obrigatório(s) ausente(s): {', '.join(missing)}")
    for name, value in arguments.items():
        _check_value(name, value, properties.get(name) or {})
    return arguments


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def audit_arguments(value, depth=0, key=None):
    """A bounded, secret-free copy of the arguments for MCPToolCallLog."""
    if key is not None and _SECRET_KEY_PATTERN.search(str(key)):
        return "[omitido]"
    if depth > AUDIT_MAX_DEPTH:
        return "[…]"
    if isinstance(value, str):
        if len(value) > AUDIT_MAX_STRING:
            return value[:AUDIT_MAX_STRING] + f"… [+{len(value) - AUDIT_MAX_STRING} caracteres]"
        return value
    if isinstance(value, dict):
        items = list(value.items())
        data = {str(k)[:100]: audit_arguments(v, depth + 1, k) for k, v in items[:AUDIT_MAX_ITEMS]}
        if len(items) > AUDIT_MAX_ITEMS:
            data["…"] = f"+{len(items) - AUDIT_MAX_ITEMS} chaves"
        return data
    if isinstance(value, list):
        data = [audit_arguments(v, depth + 1) for v in value[:AUDIT_MAX_ITEMS]]
        if len(value) > AUDIT_MAX_ITEMS:
            data.append(f"… +{len(value) - AUDIT_MAX_ITEMS} itens")
        return data
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:AUDIT_MAX_STRING]


def _log_tool_call(tool_name, arguments, status, error_message, started_at):
    try:
        MCPToolCallLog.objects.create(
            tool_name=tool_name[:255],
            arguments=audit_arguments(arguments if isinstance(arguments, dict) else {}),
            status=status,
            error_message=(error_message or "")[:AUDIT_MAX_STRING],
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
    except Exception as exc:
        log_exception(exc)


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------


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
        return _tool_error(request_id, f"Ferramenta desconhecida ou desativada: {tool_name[:100]}")

    started_at = time.monotonic()
    try:
        clean_arguments = validate_arguments(tool.input_schema, arguments)
        output = tool.handler(**clean_arguments)
        payload = {
            "content": [{"type": "text", "text": json.dumps(output, indent=2, default=str)}],
            "isError": False,
        }
        _log_tool_call(tool_name, arguments, "success", "", started_at)
        return _result(request_id, payload)
    except MCPToolError as exc:
        _log_tool_call(tool_name, arguments, "error", str(exc), started_at)
        return _tool_error(request_id, str(exc))
    except (ValidationError, DataError) as exc:
        # A value the database refuses (malformed id, text too long): the caller's input, not a crash.
        message = "Valor inválido em algum parâmetro (identificador malformado ou texto grande demais)"
        _log_tool_call(tool_name, arguments, "error", f"{message}: {exc}"[:AUDIT_MAX_STRING], started_at)
        return _tool_error(request_id, message)
    except Exception as exc:
        log_exception(exc)
        _log_tool_call(tool_name, arguments, "error", "Erro interno", started_at)
        return _tool_error(request_id, "Erro interno ao executar a ferramenta")


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

    raise MCPProtocolError(METHOD_NOT_FOUND, f"Method not found: {method[:100]}")


def handle_mcp_payload(payload, server: MCPServer):
    """Handle a JSON-RPC payload (single message or batch).

    Returns `(response, status_code)` where response is None when every
    message was a notification (HTTP 202 semantics).
    """
    is_batch = isinstance(payload, list)
    messages = payload if is_batch else [payload]

    if is_batch and not messages:
        return _error(None, INVALID_REQUEST, "Batch must not be empty"), 200
    if is_batch and len(messages) > MAX_BATCH_SIZE:
        return _error(None, INVALID_REQUEST, f"Batch must have at most {MAX_BATCH_SIZE} messages"), 200

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
