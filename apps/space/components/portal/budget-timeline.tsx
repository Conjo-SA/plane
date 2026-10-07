/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
// plane imports
import type { TIntakePortalBudgetEvent } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { BudgetNote } from "./budget-note";

const formatDateTime = (value: string) =>
  new Date(value).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

const formatHours = (hours: number) => `${Number(hours).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}h`;

const DOT: Record<TIntakePortalBudgetEvent["kind"], string> = {
  sent: "bg-accent-primary",
  revised: "bg-warning-primary",
  approved: "bg-success-primary",
  rejected: "bg-danger-primary",
  cancelled: "bg-layer-3",
};

const describe = (event: TIntakePortalBudgetEvent) => {
  switch (event.kind) {
    case "sent":
      return `Enviado: ${formatHours(event.hours)}`;
    case "revised": {
      const hoursChanged = event.previous_hours !== null && event.previous_hours !== event.hours;
      if (hoursChanged && event.note_changed)
        return `Alterado de ${formatHours(event.previous_hours!)} para ${formatHours(event.hours)} e justificativa`;
      if (hoursChanged) return `Alterado de ${formatHours(event.previous_hours!)} para ${formatHours(event.hours)}`;
      return "Justificativa alterada";
    }
    case "approved":
      return `Aprovado: ${formatHours(event.hours)}`;
    case "rejected":
      return "Recusado";
    case "cancelled":
      return "Cancelado pela equipe";
  }
};

function TimelineEvent(props: { event: TIntakePortalBudgetEvent; isLast: boolean }) {
  const { event, isLast } = props;
  const [showPrevious, setShowPrevious] = useState(false);

  return (
    <li className="relative pb-2.5 pl-5 last:pb-0">
      {!isLast && <span aria-hidden className="absolute top-3 bottom-0 left-[4px] w-px bg-layer-3" />}
      <span aria-hidden className={cn("absolute top-1.5 left-0 size-[9px] rounded-full", DOT[event.kind])} />
      <p className="text-12 text-secondary">
        <span className="font-medium text-primary">{describe(event)}</span>
        <span className="text-tertiary">
          {" · "}
          {event.actor} · {formatDateTime(event.occurred_at)}
        </span>
      </p>
      {(event.kind === "rejected" || event.kind === "cancelled") && event.reason && (
        <p className="text-12 text-secondary">Motivo: {event.reason}</p>
      )}
      {event.kind === "revised" && event.note_changed && (
        <button
          type="button"
          className="text-11 text-tertiary underline-offset-2 hover:text-primary hover:underline"
          onClick={() => setShowPrevious((value) => !value)}
        >
          {showPrevious ? "Esconder justificativa anterior" : "Ver justificativa anterior"}
        </button>
      )}
      {showPrevious && (
        <div className="mt-1 rounded-sm border border-subtle bg-surface-1 px-2.5 py-1.5">
          {event.previous_note ? (
            <BudgetNote text={event.previous_note} />
          ) : (
            <span className="text-12 text-tertiary">Sem justificativa.</span>
          )}
        </div>
      )}
    </li>
  );
}

/** What happened to an estimate, in order: sent, each edit (with the previous values), the client's answer. */
export function BudgetTimeline(props: { events: TIntakePortalBudgetEvent[]; className?: string }) {
  const { events, className } = props;
  if (events.length === 0) return null;
  return (
    <ol className={cn("mt-1", className)}>
      {events.map((event, index) => (
        <TimelineEvent key={event.id} event={event} isLast={index === events.length - 1} />
      ))}
    </ol>
  );
}
