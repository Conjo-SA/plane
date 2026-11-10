/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type {
  TMyWorkspaceAreas,
  TWorkspaceArea,
  TWorkspaceAreaConfiguration,
  TWorkspaceAreaOverrideCreate,
  TWorkspaceAreaRole,
} from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * Conjo (MAN-467): permissions by area of the workspace.
 * Errors are rethrown as the axios response, whose `data.error` carries a pt-BR message.
 * @extends {APIService}
 */
export class ConjoAreasService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  private async call<T>(promise: Promise<{ data: T }>): Promise<T> {
    return promise
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  private baseUrl(workspaceSlug: string): string {
    return `/api/workspaces/${workspaceSlug}/area-access`;
  }

  /** Areas the current user enters. */
  async getMyAreas(workspaceSlug: string): Promise<TMyWorkspaceAreas> {
    return this.call(this.get(`${this.baseUrl(workspaceSlug)}/me/`));
  }

  /** Roles per area and per-person exceptions (workspace admins only). */
  async getConfiguration(workspaceSlug: string): Promise<TWorkspaceAreaConfiguration> {
    return this.call(this.get(`${this.baseUrl(workspaceSlug)}/`));
  }

  async updateRoles(
    workspaceSlug: string,
    areas: Partial<Record<TWorkspaceArea, TWorkspaceAreaRole[]>>
  ): Promise<TWorkspaceAreaConfiguration> {
    return this.call(this.put(`${this.baseUrl(workspaceSlug)}/`, { areas }));
  }

  async saveOverride(workspaceSlug: string, data: TWorkspaceAreaOverrideCreate): Promise<TWorkspaceAreaConfiguration> {
    return this.call(this.post(`${this.baseUrl(workspaceSlug)}/overrides/`, data));
  }

  async removeOverride(workspaceSlug: string, overrideId: string): Promise<TWorkspaceAreaConfiguration> {
    return this.call(this.delete(`${this.baseUrl(workspaceSlug)}/overrides/${overrideId}/`));
  }
}
