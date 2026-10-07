/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { AxiosInstance } from "axios";
import { create, isAxiosError } from "axios";

const REQUEST_TIMEOUT_MS = 5000;

export type TAccessResult =
  | { status: "allowed"; userId: string; restricted: boolean }
  | { status: "unauthenticated" }
  | { status: "forbidden" }
  | { status: "unavailable" };

/**
 * Asks the API, with the browser's own session cookie, who the user is and whether they may
 * follow a project. Permissions stay in one place (the API); the live server only relays.
 */
export class RealtimeAccessService {
  private readonly http: AxiosInstance;

  constructor(baseURL: string) {
    this.http = create({ baseURL, timeout: REQUEST_TIMEOUT_MS, maxRedirects: 0 });
  }

  private classify(status: number | undefined): TAccessResult {
    if (status === 401) return { status: "unauthenticated" };
    if (status === 403 || status === 404) return { status: "forbidden" };
    return { status: "unavailable" };
  }

  /** The id of the user the session belongs to, or null when it is not a valid session. */
  async currentUserId(cookie: string): Promise<string | null | "unavailable"> {
    try {
      const response = await this.http.get("/api/users/me/", { headers: { Cookie: cookie } });
      const id = response.data?.id;
      return typeof id === "string" && id ? id : null;
    } catch (error) {
      const status = isAxiosError(error) ? error.response?.status : undefined;
      if (status === 401 || status === 403) return null;
      return "unavailable";
    }
  }

  async projectAccess(cookie: string, workspaceSlug: string, projectId: string): Promise<TAccessResult> {
    try {
      const response = await this.http.get(
        `/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${encodeURIComponent(projectId)}/realtime-access/`,
        { headers: { Cookie: cookie } }
      );
      const userId = response.data?.user_id;
      if (typeof userId !== "string" || response.data?.project_id !== projectId) return { status: "forbidden" };
      return { status: "allowed", userId, restricted: response.data?.restricted !== false };
    } catch (error) {
      return this.classify(isAxiosError(error) ? error.response?.status : undefined);
    }
  }
}
