/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
// lib
import { realtimeConnection } from "@/lib/realtime/connection";
import { realtimeIssueSync } from "@/lib/realtime/issue-sync";

let unsubscribe: (() => void) | null = null;

const ensureSubscribed = () => {
  if (unsubscribe) return;
  unsubscribe = realtimeConnection.subscribe({
    onEvent: realtimeIssueSync.handleEvent,
    onResync: realtimeIssueSync.resync,
  });
};

/**
 * Follows a project's work item changes in realtime while the component is mounted:
 * boards, lists, spreadsheet, calendar and the open work item update for everyone.
 */
export const useProjectRealtime = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  useEffect(() => {
    if (!workspaceSlug || !projectId) return;
    ensureSubscribed();
    return realtimeConnection.joinProject(workspaceSlug, projectId);
  }, [workspaceSlug, projectId]);
};
