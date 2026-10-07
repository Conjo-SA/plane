/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TCalendarLayouts } from "@plane/types";
import { EStartOfTheWeek } from "@plane/types";

export const MONTHS_LIST: {
  [monthNumber: number]: {
    shortTitle: string;
    title: string;
  };
} = {
  1: {
    shortTitle: "Jan",
    title: "Janeiro",
  },
  2: {
    shortTitle: "Fev",
    title: "Fevereiro",
  },
  3: {
    shortTitle: "Mar",
    title: "Março",
  },
  4: {
    shortTitle: "Abr",
    title: "Abril",
  },
  5: {
    shortTitle: "Mai",
    title: "Maio",
  },
  6: {
    shortTitle: "Jun",
    title: "Junho",
  },
  7: {
    shortTitle: "Jul",
    title: "Julho",
  },
  8: {
    shortTitle: "Ago",
    title: "Agosto",
  },
  9: {
    shortTitle: "Set",
    title: "Setembro",
  },
  10: {
    shortTitle: "Out",
    title: "Outubro",
  },
  11: {
    shortTitle: "Nov",
    title: "Novembro",
  },
  12: {
    shortTitle: "Dez",
    title: "Dezembro",
  },
};

export const DAYS_LIST: {
  [dayIndex: number]: {
    shortTitle: string;
    title: string;
    value: EStartOfTheWeek;
  };
} = {
  1: {
    shortTitle: "Dom",
    title: "Domingo",
    value: EStartOfTheWeek.SUNDAY,
  },
  2: {
    shortTitle: "Seg",
    title: "Segunda-feira",
    value: EStartOfTheWeek.MONDAY,
  },
  3: {
    shortTitle: "Ter",
    title: "Terça-feira",
    value: EStartOfTheWeek.TUESDAY,
  },
  4: {
    shortTitle: "Qua",
    title: "Quarta-feira",
    value: EStartOfTheWeek.WEDNESDAY,
  },
  5: {
    shortTitle: "Qui",
    title: "Quinta-feira",
    value: EStartOfTheWeek.THURSDAY,
  },
  6: {
    shortTitle: "Sex",
    title: "Sexta-feira",
    value: EStartOfTheWeek.FRIDAY,
  },
  7: {
    shortTitle: "Sáb",
    title: "Sábado",
    value: EStartOfTheWeek.SATURDAY,
  },
};

export const CALENDAR_LAYOUTS: {
  [layout in TCalendarLayouts]: {
    key: TCalendarLayouts;
    title: string;
  };
} = {
  month: {
    key: "month",
    title: "Layout mensal",
  },
  week: {
    key: "week",
    title: "Layout semanal",
  },
};
