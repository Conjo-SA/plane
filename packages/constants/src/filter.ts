/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export enum E_SORT_ORDER {
  ASC = "asc",
  DESC = "desc",
}
export const DATE_AFTER_FILTER_OPTIONS = [
  {
    name: "Daqui a 1 semana",
    value: "1_weeks;after;fromnow",
  },
  {
    name: "Daqui a 2 semanas",
    value: "2_weeks;after;fromnow",
  },
  {
    name: "Daqui a 1 mês",
    value: "1_months;after;fromnow",
  },
  {
    name: "Daqui a 2 meses",
    value: "2_months;after;fromnow",
  },
];

export const DATE_BEFORE_FILTER_OPTIONS = [
  {
    name: "Há 1 semana",
    value: "1_weeks;before;fromnow",
  },
  {
    name: "Há 2 semanas",
    value: "2_weeks;before;fromnow",
  },
  {
    name: "Há 1 mês",
    i18n_name: "date_filters.1_month_ago",
    value: "1_months;before;fromnow",
  },
];

export const PROJECT_CREATED_AT_FILTER_OPTIONS = [
  {
    name: "Hoje",
    value: "today;custom;custom",
  },
  {
    name: "Ontem",
    value: "yesterday;custom;custom",
  },
  {
    name: "Últimos 7 dias",
    value: "last_7_days;custom;custom",
  },
  {
    name: "Últimos 30 dias",
    value: "last_30_days;custom;custom",
  },
];
