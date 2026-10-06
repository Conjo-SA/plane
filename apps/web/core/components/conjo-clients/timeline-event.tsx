/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import {
  Check,
  CircleCheck,
  CircleX,
  FileText,
  GitPullRequest,
  Inbox,
  Mail,
  Phone,
  StickyNote,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";
// plane imports
import type { TClientNoteKind, TClientTimelineEvent, TIssueRef } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import {
  WORK_KIND_LABEL,
  formatDayMonth,
  formatHours,
  formatMinutes,
  formatSignedHours,
  formatTime,
  issueHref,
  joinNames,
  toHours,
} from "./helpers";
import { NOTE_KIND_LABEL } from "./note-modal";

const NOTE_ICON: Record<TClientNoteKind, typeof Users> = {
  meeting: Users,
  call: Phone,
  email: Mail,
  note: StickyNote,
};

type Props = {
  event: TClientTimelineEvent;
  workspaceSlug: string;
  /** Shows the delete button on notes (the API still checks author/admin). */
  canDeleteNote?: (author: string) => boolean;
  onDeleteNote?: (noteId: string) => void;
};

function IssueLink({ workspaceSlug, issue }: { workspaceSlug: string; issue: TIssueRef }) {
  return (
    <>
      <Link href={issueHref(workspaceSlug, issue)} className="font-medium text-accent-primary hover:underline">
        {issue.key}
      </Link>{" "}
      {issue.name}
    </>
  );
}

/** Round marker on the left of each event: an icon or the signed hours. */
function Marker({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full text-11 font-semibold",
        className
      )}
      aria-hidden
    >
      {children}
    </span>
  );
}

type TRendered = { marker: ReactNode; title: ReactNode; body?: ReactNode; details: (string | ReactNode)[] };

const iconClass = "size-4";

function renderEvent(event: TClientTimelineEvent, workspaceSlug: string): TRendered {
  switch (event.type) {
    case "note": {
      const Icon = NOTE_ICON[event.kind];
      return {
        marker: (
          <Marker className="bg-layer-3 text-primary">
            <Icon className={iconClass} />
          </Marker>
        ),
        title: (
          <>
            <b className="font-semibold">{NOTE_KIND_LABEL[event.kind]}</b>
            {event.contacts.length > 0 && <> com {joinNames(event.contacts)}</>}
            {event.author && <> · registrada por {event.author}</>}
          </>
        ),
        body: event.body,
        details: [],
      };
    }
    case "ledger":
      return renderLedgerEvent(event, workspaceSlug);
    case "request":
      return {
        marker: (
          <Marker className="bg-layer-3 text-primary">
            <Inbox className={iconClass} />
          </Marker>
        ),
        title: (
          <>
            <b className="font-semibold">Solicitação aberta pela Entrada</b>
            {event.requester && <> por {event.requester}</>} ·{" "}
            <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
          </>
        ),
        details: [],
      };
    case "estimate_sent":
      return {
        marker: (
          <Marker className="bg-layer-3 text-primary">
            <FileText className={iconClass} />
          </Marker>
        ),
        title: (
          <>
            <b className="font-semibold">Orçamento enviado</b> ·{" "}
            <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
          </>
        ),
        details: [`${formatHours(event.hours)} orçadas, aguardando aprovação do cliente`],
      };
    case "estimate_approved":
      return {
        marker: (
          <Marker className="bg-success-subtle text-success-primary">
            <CircleCheck className={iconClass} />
          </Marker>
        ),
        title: (
          <>
            <b className="font-semibold">Orçamento aprovado</b>
            {event.by && <> por {event.by}</>} · <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
          </>
        ),
        details: [`${formatHours(event.hours)} debitadas do crédito que vence primeiro`],
      };
    case "estimate_rejected":
      return {
        marker: (
          <Marker className="bg-danger-subtle text-danger-primary">
            <CircleX className={iconClass} />
          </Marker>
        ),
        title: (
          <>
            <b className="font-semibold">Orçamento recusado</b>
            {event.by && <> por {event.by}</>} · <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
          </>
        ),
        details: [`${formatHours(event.hours)} orçadas`, event.reason ? `motivo: ${event.reason}` : null],
      };
    case "delivered": {
      const debits = event.kind === "evolution" || event.kind === null;
      const spent = event.minutes > 0 ? formatMinutes(event.minutes) : null;
      const estimated = event.estimated_hours ? formatHours(event.estimated_hours) : null;
      const deviation = estimated && spent ? event.minutes / 60 - toHours(event.estimated_hours) : 0;
      return {
        marker: debits ? (
          <Marker className="bg-success-subtle text-success-primary">
            <Check className={iconClass} strokeWidth={2.4} />
          </Marker>
        ) : (
          <Marker className="border border-dashed border-strong text-secondary">
            {spent ?? <Check className={iconClass} />}
          </Marker>
        ),
        title: (
          <>
            <b className="font-semibold">Entrega concluída</b> ·{" "}
            <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
          </>
        ),
        details: [
          event.kind ? WORK_KIND_LABEL[event.kind] : null,
          estimated && spent
            ? `orçado ${estimated} · gasto ${spent}${
                Math.abs(deviation) >= 0.25 ? ` (${formatSignedHours(deviation)} de desvio)` : ""
              }`
            : spent
              ? `${spent} registradas`
              : estimated
                ? `orçado ${estimated}`
                : null,
          debits ? null : "não desconta do pacote",
        ],
      };
    }
    case "pr_merged":
      return {
        marker: (
          <Marker className="bg-layer-3 text-primary">
            <GitPullRequest className={iconClass} />
          </Marker>
        ),
        title: (
          <>
            <a href={event.url} target="_blank" rel="noopener noreferrer" className="font-semibold hover:underline">
              PR #{event.number} mergeado
            </a>{" "}
            · <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
          </>
        ),
        details: [event.title, event.repository, event.author ? `por ${event.author}` : null],
      };
  }
}

function renderLedgerEvent(event: Extract<TClientTimelineEvent, { type: "ledger" }>, workspaceSlug: string): TRendered {
  const issue = event.issue ? (
    <>
      {" "}
      · <IssueLink workspaceSlug={workspaceSlug} issue={event.issue} />
    </>
  ) : null;
  const note = event.note || null;
  switch (event.kind) {
    case "credit":
      return {
        marker: <Marker className="bg-success-subtle text-success-primary">{formatSignedHours(event.hours)}</Marker>,
        title: <b className="font-semibold">Crédito mensal</b>,
        details: [
          formatSignedHours(event.hours),
          event.expires_on ? `vale até ${formatDayMonth(event.expires_on)}` : null,
          note,
        ],
      };
    case "debit":
      return {
        marker: <Marker className="bg-inverse text-inverse">{formatSignedHours(event.hours)}</Marker>,
        title: (
          <>
            <b className="font-semibold">Débito</b>
            {issue}
          </>
        ),
        details: [`${formatHours(event.hours)} debitadas do pacote`, note],
      };
    case "expiration":
      return {
        marker: <Marker className="bg-warning-subtle text-warning-primary">{formatSignedHours(event.hours)}</Marker>,
        title: <b className="font-semibold">Expiração</b>,
        details: [`${formatHours(event.hours)} não usadas dentro da validade`, note],
      };
    case "reversal":
      return {
        marker: <Marker className="bg-layer-3 text-secondary">{formatSignedHours(event.hours)}</Marker>,
        title: (
          <>
            <b className="font-semibold">Estorno</b>
            {issue}
          </>
        ),
        details: [`${formatHours(event.hours)} voltaram para o saldo`, note],
      };
    case "adjustment":
      return {
        marker: <Marker className="bg-accent-subtle text-accent-primary">{formatSignedHours(event.hours)}</Marker>,
        title: <b className="font-semibold">Ajuste manual</b>,
        details: [formatSignedHours(event.hours), note],
      };
    case "excess":
      return {
        marker: <Marker className="bg-danger-subtle text-danger-primary">{formatHours(event.hours)}</Marker>,
        title: (
          <>
            <b className="font-semibold">Excedente</b>
            {issue}
          </>
        ),
        details: [`${formatHours(event.hours)} além do saldo, cobradas pelo financeiro`, note],
      };
  }
}

export function TimelineEvent({ event, workspaceSlug, canDeleteNote, onDeleteNote }: Props) {
  const { marker, title, body, details } = renderEvent(event, workspaceSlug);
  // Statement entries are dated, not timed: showing a clock time there would be invented.
  const time = event.type === "ledger" ? "" : formatTime(event.at);
  const detailLine = [...details.filter(Boolean), time].filter(Boolean);
  const showDelete = event.type === "note" && !!onDeleteNote && !!canDeleteNote?.(event.author);

  return (
    <li className="flex gap-3.5 border-b border-subtle py-3 last:border-b-0">
      {marker}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-13 break-words text-primary">{title}</span>
        {body && (
          <p className="rounded-md bg-layer-2 px-2.5 py-2 text-13 break-words whitespace-pre-wrap text-secondary">
            {body}
          </p>
        )}
        <span className="text-12 text-tertiary">
          {detailLine.map((part, index) => (
            // oxlint-disable-next-line react/no-array-index-key
            <span key={index}>
              {index > 0 && " · "}
              {part}
            </span>
          ))}
        </span>
      </div>
      {showDelete && event.type === "note" && (
        <button
          type="button"
          className="self-start rounded-sm p-1 text-tertiary hover:bg-layer-1-hover hover:text-danger-primary"
          onClick={() => onDeleteNote?.(event.id)}
          aria-label="Excluir registro"
          title="Excluir registro"
        >
          <Trash2 className="size-3.5" />
        </button>
      )}
    </li>
  );
}
