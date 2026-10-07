/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssueActivity } from "@plane/types";

export const getRelationActivityContent = (activity: TIssueActivity | undefined): string | undefined => {
  if (!activity) return;

  switch (activity.field) {
    case "blocking":
      return activity.old_value === "" ? `marcou que esta tarefa bloqueia a tarefa ` : `removeu a tarefa bloqueada `;
    case "blocked_by":
      return activity.old_value === ""
        ? `marcou que esta tarefa está bloqueada por `
        : `removeu o bloqueio desta tarefa pela tarefa `;
    case "duplicate":
      return activity.old_value === ""
        ? `marcou esta tarefa como duplicada de `
        : `removeu esta tarefa como duplicada de `;
    case "relates_to":
      return activity.old_value === "" ? `marcou esta tarefa como relacionada a ` : `removeu a relação com `;
  }

  return;
};
