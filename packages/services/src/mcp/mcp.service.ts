/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type { IMCPServerConfig, IMCPTestConnectionResult, IMCPToolCallLog, IMCPToolDefinition } from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * Service class for managing the instance-level MCP server (God Mode).
 * Handles connector configuration, tool catalog, connection tests and call logs.
 * @extends {APIService}
 */
export class MCPService extends APIService {
  /**
   * Creates an instance of MCPService
   * Initializes the service with the base API URL
   */
  constructor() {
    super(API_BASE_URL);
  }

  /**
   * Retrieves the MCP server configuration (creates it on first access)
   * @returns {Promise<IMCPServerConfig>} Promise resolving to the MCP server config
   * @throws {Error} If the API request fails
   */
  async config(): Promise<IMCPServerConfig> {
    return this.get("/api/mcp/config/")
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Updates the MCP server configuration
   * @param {Partial<IMCPServerConfig>} data Configuration fields to update
   * @returns {Promise<IMCPServerConfig>} Promise resolving to the updated config
   * @throws {Error} If the API request fails
   */
  async updateConfig(data: Partial<IMCPServerConfig>): Promise<IMCPServerConfig> {
    return this.patch("/api/mcp/config/", data)
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Rotates the MCP bearer token
   * @returns {Promise<IMCPServerConfig>} Promise resolving to the config with the new token
   * @throws {Error} If the API request fails
   */
  async regenerateToken(): Promise<IMCPServerConfig> {
    return this.post("/api/mcp/config/regenerate-token/")
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Lists every registered MCP tool and whether it is enabled
   * @returns {Promise<{ tools: IMCPToolDefinition[] }>} Promise resolving to the tool catalog
   * @throws {Error} If the API request fails
   */
  async tools(): Promise<{ tools: IMCPToolDefinition[] }> {
    return this.get("/api/mcp/tools/")
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Runs a synthetic MCP handshake to verify the server configuration
   * @returns {Promise<IMCPTestConnectionResult>} Promise resolving to the test result
   * @throws {Error} If the API request fails
   */
  async testConnection(): Promise<IMCPTestConnectionResult> {
    return this.post("/api/mcp/test/")
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Fetches the most recent MCP tool call logs
   * @param {number} limit Maximum number of log entries (default 50)
   * @returns {Promise<{ logs: IMCPToolCallLog[] }>} Promise resolving to the call logs
   * @throws {Error} If the API request fails
   */
  async logs(limit: number = 50): Promise<{ logs: IMCPToolCallLog[] }> {
    return this.get("/api/mcp/logs/", { params: { limit } })
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Clears the MCP tool call log
   * @returns {Promise<void>} Promise resolving when the log is cleared
   * @throws {Error} If the API request fails
   */
  async clearLogs(): Promise<void> {
    return this.delete("/api/mcp/logs/")
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

export const mcpService = new MCPService();
