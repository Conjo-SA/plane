/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// types
import type { TIssuesListTypes } from "@plane/types";

export enum EDurationFilters {
  NONE = "none",
  TODAY = "today",
  THIS_WEEK = "this_week",
  THIS_MONTH = "this_month",
  THIS_YEAR = "this_year",
  CUSTOM = "custom",
}

// filter duration options
export const DURATION_FILTER_OPTIONS: {
  key: EDurationFilters;
  label: string;
}[] = [
  {
    key: EDurationFilters.NONE,
    label: "Todo o período",
  },
  {
    key: EDurationFilters.TODAY,
    label: "Vence hoje",
  },
  {
    key: EDurationFilters.THIS_WEEK,
    label: "Vence esta semana",
  },
  {
    key: EDurationFilters.THIS_MONTH,
    label: "Vence este mês",
  },
  {
    key: EDurationFilters.THIS_YEAR,
    label: "Vence este ano",
  },
  {
    key: EDurationFilters.CUSTOM,
    label: "Personalizado",
  },
];

// random background colors for project cards
export const PROJECT_BACKGROUND_COLORS = [
  "bg-gray-500/20",
  "bg-success-subtle",
  "bg-danger-subtle",
  "bg-orange-500/20",
  "bg-blue-500/20",
  "bg-yellow-500/20",
  "bg-pink-500/20",
  "bg-purple-500/20",
];

// assigned and created issues widgets tabs list
export const FILTERED_ISSUES_TABS_LIST: {
  key: TIssuesListTypes;
  label: string;
}[] = [
  {
    key: "upcoming",
    label: "Próximas",
  },
  {
    key: "overdue",
    label: "Atrasadas",
  },
  {
    key: "completed",
    label: "Concluídas",
  },
];

// assigned and created issues widgets tabs list
export const UNFILTERED_ISSUES_TABS_LIST: {
  key: TIssuesListTypes;
  label: string;
}[] = [
  {
    key: "pending",
    label: "Pendentes",
  },
  {
    key: "completed",
    label: "Concluídas",
  },
];

export type TLinkOptions = {
  userId: string | undefined;
};
