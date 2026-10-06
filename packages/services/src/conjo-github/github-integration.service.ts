/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type { TIssueDevelopment, TProjectGitHubSettings, TProjectGitHubSettingsUpdate } from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * Service class for the GitHub integration (development panel and project settings).
 * Errors are rethrown as the axios response, whose `data.error` carries a pt-BR message.
 * @extends {APIService}
 */
export class GitHubIntegrationService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  private settingsUrl(workspaceSlug: string, projectId: string): string {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/github-integration/`;
  }

  /**
   * Retrieves the GitHub settings of a project (smart commits and pull request automations).
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @returns {Promise<TProjectGitHubSettings>} The settings
   * @throws {Error} If the API request fails
   */
  async retrieveSettings(workspaceSlug: string, projectId: string): Promise<TProjectGitHubSettings> {
    return this.get(this.settingsUrl(workspaceSlug, projectId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  /**
   * Updates the GitHub settings of a project.
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @param {TProjectGitHubSettingsUpdate} data - The fields to update
   * @returns {Promise<TProjectGitHubSettings>} The updated settings
   * @throws {Error} If the API request fails
   */
  async updateSettings(
    workspaceSlug: string,
    projectId: string,
    data: TProjectGitHubSettingsUpdate
  ): Promise<TProjectGitHubSettings> {
    return this.patch(this.settingsUrl(workspaceSlug, projectId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  /**
   * Lists the branches, commits and pull requests linked to a work item.
   * @param {string} workspaceSlug - The workspace slug
   * @param {string} projectId - The project identifier
   * @param {string} issueId - The work item identifier
   * @returns {Promise<TIssueDevelopment>} The linked development items
   * @throws {Error} If the API request fails
   */
  async retrieveIssueDevelopment(
    workspaceSlug: string,
    projectId: string,
    issueId: string
  ): Promise<TIssueDevelopment> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/development/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }
}
