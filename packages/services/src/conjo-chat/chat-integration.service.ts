/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type {
  TProjectChatIntegration,
  TProjectChatIntegrationTestResponse,
  TProjectChatIntegrationUpdate,
} from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * Service class for the Conjo Chat (Matrix) integration of a project.
 * Errors are rethrown as the axios response, whose `data.error` carries a pt-BR message.
 * @extends {APIService}
 */
export class ProjectChatIntegrationService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  private baseUrl(workspaceSlug: string, projectId: string): string {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/chat-integration/`;
  }

  /**
   * Retrieves the chat integration of a project (defaults when not configured yet).
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @returns {Promise<TProjectChatIntegration>} The integration
   * @throws {Error} If the API request fails
   */
  async retrieve(workspaceSlug: string, projectId: string): Promise<TProjectChatIntegration> {
    return this.get(this.baseUrl(workspaceSlug, projectId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  /**
   * Updates the notice switches of the integration.
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @param {TProjectChatIntegrationUpdate} data - The fields to update
   * @returns {Promise<TProjectChatIntegration>} The updated integration
   * @throws {Error} If the API request fails
   */
  async update(
    workspaceSlug: string,
    projectId: string,
    data: TProjectChatIntegrationUpdate
  ): Promise<TProjectChatIntegration> {
    return this.patch(this.baseUrl(workspaceSlug, projectId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  /**
   * Creates the project room in the chat, or reapplies its name, state and widget when it exists.
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @returns {Promise<TProjectChatIntegration>} The integration with the room
   * @throws {Error} If the API request fails
   */
  async createRoom(workspaceSlug: string, projectId: string): Promise<TProjectChatIntegration> {
    return this.post(`${this.baseUrl(workspaceSlug, projectId)}create-room/`, {})
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  /**
   * Sends a test message to the project room.
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @returns {Promise<TProjectChatIntegrationTestResponse>} `{ ok: true }` on success
   * @throws {Error} If the API request fails
   */
  async sendTest(workspaceSlug: string, projectId: string): Promise<TProjectChatIntegrationTestResponse> {
    return this.post(`${this.baseUrl(workspaceSlug, projectId)}test/`, {})
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }
}
