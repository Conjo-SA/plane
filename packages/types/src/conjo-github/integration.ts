/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TDevelopmentLinkKind = "branch" | "commit" | "pull_request";

export type TDevelopmentLink = {
  id: string;
  kind: TDevelopmentLinkKind;
  /** "owner/name" */
  repository: string;
  /** Branch name, commit sha or pull request number. */
  external_id: string;
  title: string;
  url: string;
  /** open | draft | merged | closed (pull requests), open | deleted (branches) */
  state: string;
  author_login: string;
  author_name: string;
  author_avatar_url: string;
  event_at: string | null;
  metadata: Record<string, string>;
};

export type TIssueDevelopment = {
  branches: TDevelopmentLink[];
  commits: TDevelopmentLink[];
  pull_requests: TDevelopmentLink[];
  /** Suggested branch name, e.g. "man-12-corrigir-login". */
  branch_name: string;
  github_configured: boolean;
};

export type TProjectGitHubSettings = {
  id: string;
  project: string;
  smart_commits: boolean;
  pr_opened_state: string | null;
  pr_merged_state: string | null;
  /** False when the server has no CONJO_GITHUB_WEBHOOK_SECRET. */
  webhook_configured: boolean;
  webhook_url: string;
  last_event: { event: string; repository: string; at: string } | null;
  project_identifier: string;
};

export type TProjectGitHubSettingsUpdate = Partial<
  Pick<TProjectGitHubSettings, "smart_commits" | "pr_opened_state" | "pr_merged_state">
>;
