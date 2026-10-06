/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { GitMerge, GitPullRequest, GitPullRequestClosed, GitPullRequestDraft } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type TPullRequestState = "open" | "draft" | "merged" | "closed";

type TPullRequestStateMeta = {
  label: string;
  /** Summary/card wording, e.g. "1 mergeado". */
  plural: [string, string];
  Icon: LucideIcon;
  /** Icon and text color. */
  text: string;
  /** Filled pill (status badge). */
  pill: string;
  /** Soft chip (cards on the board). */
  chip: string;
};

export const PR_STATES: Record<TPullRequestState, TPullRequestStateMeta> = {
  open: {
    label: "Aberto",
    plural: ["aberto", "abertos"],
    Icon: GitPullRequest,
    text: "text-success-primary",
    pill: "bg-success-primary text-on-color",
    chip: "bg-success-subtle text-success-primary",
  },
  draft: {
    label: "Rascunho",
    plural: ["rascunho", "rascunhos"],
    Icon: GitPullRequestDraft,
    text: "text-tertiary",
    pill: "bg-layer-3 text-secondary",
    chip: "bg-layer-2 text-secondary",
  },
  merged: {
    label: "Mergeado",
    plural: ["mergeado", "mergeados"],
    Icon: GitMerge,
    text: "text-[#8250df]",
    pill: "bg-[#8250df] text-white",
    chip: "bg-[#8250df]/10 text-[#8250df]",
  },
  closed: {
    label: "Fechado",
    plural: ["fechado", "fechados"],
    Icon: GitPullRequestClosed,
    text: "text-danger-primary",
    pill: "bg-danger-primary text-on-color",
    chip: "bg-danger-subtle text-danger-primary",
  },
};

export const prStateMeta = (state: string | null | undefined): TPullRequestStateMeta =>
  PR_STATES[(state as TPullRequestState) ?? "open"] ?? PR_STATES.open;

export const relativeTime = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const format = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "agora";
};
