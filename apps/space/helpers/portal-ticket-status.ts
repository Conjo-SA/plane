/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIntakePortalTicket } from "@plane/types";

export type TPortalTicketBucket = "action" | "open" | "closed";

export type TPortalTicketStatus = {
  bucket: TPortalTicketBucket;
  label: string;
  /** Short explanation shown under the title, in the requester's words. */
  hint: string | null;
  color: string;
};

// Intake statuses (IntakeIssueStatus on the backend).
const INTAKE_PENDING = -2;
const INTAKE_REJECTED = -1;
const INTAKE_SNOOZED = 0;
const INTAKE_DUPLICATE = 2;

const COLORS = {
  action: "#C2410C",
  review: "#7C3AED",
  queue: "#2563EB",
  progress: "#D97706",
  done: "#15803D",
  closed: "#6B7280",
};

/**
 * Where a ticket stands from the requester's point of view: does it need them, is it still being handled,
 * or is it finished. Internal workflow names (backlog, triage...) never reach the requester.
 */
export const getPortalTicketStatus = (ticket: TIntakePortalTicket): TPortalTicketStatus => {
  const group = ticket.state_group ?? "";

  if (ticket.intake_status === INTAKE_REJECTED)
    return { bucket: "closed", label: "Não aceito", hint: null, color: COLORS.closed };
  if (ticket.intake_status === INTAKE_DUPLICATE)
    return { bucket: "closed", label: "Duplicado", hint: "Já tratado em outro chamado", color: COLORS.closed };
  if (group === "completed") return { bucket: "closed", label: "Concluído", hint: null, color: COLORS.done };
  if (group === "cancelled") return { bucket: "closed", label: "Cancelado", hint: null, color: COLORS.closed };

  if (ticket.budget_status === "PENDING")
    return {
      bucket: "action",
      label: "Orçamento para aprovar",
      hint: ticket.budget_hours ? `${formatHours(ticket.budget_hours)} orçadas, aguardando sua resposta` : null,
      color: COLORS.action,
    };

  if (ticket.intake_status === INTAKE_PENDING || ticket.intake_status === INTAKE_SNOOZED || group === "triage")
    return { bucket: "open", label: "Em análise", hint: "A equipe está avaliando o pedido", color: COLORS.review };
  if (group === "started")
    return { bucket: "open", label: "Em andamento", hint: "Alguém já está trabalhando nisso", color: COLORS.progress };
  return { bucket: "open", label: "Na fila", hint: "Aceito, aguardando para começar", color: COLORS.queue };
};

const formatHours = (value: string) => {
  const hours = Number(value);
  if (!Number.isFinite(hours)) return `${value}h`;
  return `${hours.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}h`;
};
