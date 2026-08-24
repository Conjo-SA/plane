/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Instance-level MCP (Model Context Protocol) server configuration.
 */
export interface IMCPServerConfig {
  id: string;
  name: string;
  description: string;
  is_enabled: boolean;
  token: string;
  disabled_tools: string[];
  created_at: string;
  updated_at: string;
}

export interface IMCPToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: string;
    properties?: Record<string, unknown>;
    required?: string[];
    additionalProperties?: boolean;
  };
  category: string;
  is_enabled: boolean;
}

export interface IMCPToolCallLog {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: "success" | "error";
  error_message: string;
  duration_ms: number;
  created_at: string;
}

export interface IMCPTestConnectionResult {
  success: boolean;
  is_enabled: boolean;
  protocol_version: string;
  server_info: {
    name: string;
    title: string;
    version: string;
  };
  tool_count: number;
  tools: string[];
  latency_ms: number;
}
