/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Conjo Chat (Matrix) integration of a project: the room that receives the
 * project notices and which kinds of notices are sent to it.
 */
export type TProjectChatIntegration = {
  id: string | null;
  project: string;
  enabled: boolean;
  room_id: string | null;
  room_name: string | null;
  room_url: string | null;
  notify_issue_created: boolean;
  notify_state_changed: boolean;
  notify_assignee_changed: boolean;
  notify_comment_created: boolean;
  /** Pull requests opened/merged on GitHub that mention a work item. */
  notify_github: boolean;
  /** False when the server has no CONJO_CHAT_* variables, so nothing can be configured. */
  chat_configured: boolean;
};

export type TProjectChatIntegrationNotifyKey =
  | "notify_issue_created"
  | "notify_state_changed"
  | "notify_assignee_changed"
  | "notify_comment_created"
  | "notify_github";

/** Fields a project admin can change through PATCH. */
export type TProjectChatIntegrationUpdate = Partial<
  Pick<TProjectChatIntegration, "enabled" | TProjectChatIntegrationNotifyKey>
>;

export type TProjectChatIntegrationTestResponse = {
  ok: boolean;
};
