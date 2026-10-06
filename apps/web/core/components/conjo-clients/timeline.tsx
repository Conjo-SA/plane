/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { History } from "lucide-react";
import useSWRInfinite from "swr/infinite";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClientTimeline, TClientTimelineEvent, TClientTimelineType } from "@plane/types";
import { AlertModalCore, Loader } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { EmptyState } from "./common";
import { conjoBillingService, dayKey, formatDayLabel, getErrorMessage } from "./helpers";
import { TimelineEvent } from "./timeline-event";

const PAGE_SIZE = 40;

const FILTERS: { key: TClientTimelineType | null; label: string }[] = [
  { key: null, label: "Tudo" },
  { key: "requests", label: "Solicitações" },
  { key: "hours", label: "Horas" },
  { key: "contacts", label: "Contatos" },
  { key: "deliveries", label: "Entregas" },
];

type Props = {
  workspaceSlug: string;
  clientId: string;
  isAdmin: boolean;
  /** Display name of the current user, to offer deleting their own notes. */
  currentUserName?: string;
  /** Bumped by the parent after a note is registered, to reload the first page. */
  refreshToken: number;
};

/** SWR key of each page: the filter and the `before` cursor of the previous page. */
type TPageKey = [string, string, TClientTimelineType | null, string | undefined, number];

export function ClientTimeline({ workspaceSlug, clientId, isAdmin, currentUserName, refreshToken }: Props) {
  const [filter, setFilter] = useState<TClientTimelineType | null>(null);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const getKey = (pageIndex: number, previous: TClientTimeline | null): TPageKey | null => {
    if (previous && !previous.next_before) return null;
    return [
      "CONJO_CLIENT_TIMELINE",
      `${workspaceSlug}_${clientId}`,
      filter,
      pageIndex === 0 ? undefined : (previous?.next_before ?? undefined),
      refreshToken,
    ];
  };

  const { data, error, size, setSize, isValidating, mutate } = useSWRInfinite(
    getKey,
    ([, , type, before]: TPageKey) =>
      conjoBillingService.getTimeline(workspaceSlug, clientId, {
        types: type ? [type] : undefined,
        before,
        limit: PAGE_SIZE,
      }),
    { revalidateOnFocus: false, revalidateFirstPage: false }
  );

  const groups = useMemo(() => {
    const result: { day: string; events: TClientTimelineEvent[] }[] = [];
    for (const event of (data ?? []).flatMap((page) => page.events)) {
      const day = dayKey(event.at);
      const last = result[result.length - 1];
      if (last && last.day === day) last.events.push(event);
      else result.push({ day, events: [event] });
    }
    return result;
  }, [data]);

  const hasMore = !!data?.[data.length - 1]?.next_before;
  const isLoadingMore = isValidating && !!data && size > data.length;

  const handleDeleteNote = async () => {
    if (!deletingNoteId) return;
    setIsDeleting(true);
    try {
      await conjoBillingService.deleteTimelineNote(workspaceSlug, clientId, deletingNoteId);
      await mutate();
      setDeletingNoteId(null);
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível excluir o registro."),
      });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <section className="flex min-w-0 flex-col gap-4 rounded-lg border border-subtle bg-layer-1 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-16 font-semibold text-primary">Linha do tempo</h2>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrar linha do tempo">
          {FILTERS.map((option) => (
            <button
              key={option.label}
              type="button"
              aria-pressed={filter === option.key}
              onClick={() => setFilter(option.key)}
              className={cn("min-h-8 rounded-full border px-3 py-1 text-13 transition-colors", {
                "border-transparent bg-inverse text-inverse": filter === option.key,
                "border-subtle text-secondary hover:bg-layer-1-hover": filter !== option.key,
              })}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {error && !data ? (
        <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
          {getErrorMessage(error, "Não foi possível carregar a linha do tempo.")}
        </div>
      ) : !data ? (
        <Loader className="space-y-3">
          <Loader.Item height="48px" width="100%" />
          <Loader.Item height="48px" width="100%" />
          <Loader.Item height="48px" width="100%" />
          <Loader.Item height="48px" width="100%" />
        </Loader>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<History className="size-6" />}
          title={filter ? "Nada deste tipo por aqui" : "A linha do tempo está vazia"}
          description="Solicitações da Entrada, orçamentos, horas, entregas, PRs e contatos registrados aparecem aqui."
        />
      ) : (
        <div className="flex flex-col">
          {groups.map((group) => (
            <div key={group.day} className="flex flex-col">
              <h3 className="pt-3 pb-1 text-12 font-semibold text-tertiary first:pt-0">{formatDayLabel(group.day)}</h3>
              <ul className="flex flex-col">
                {group.events.map((event, index) => (
                  <TimelineEvent
                    // events have no common id; type + time + position is stable within a page
                    // oxlint-disable-next-line react/no-array-index-key
                    key={`${event.type}-${event.at}-${index}`}
                    event={event}
                    workspaceSlug={workspaceSlug}
                    canDeleteNote={(author) => isAdmin || (!!currentUserName && author === currentUserName)}
                    onDeleteNote={setDeletingNoteId}
                  />
                ))}
              </ul>
            </div>
          ))}
          {hasMore && (
            <div className="flex justify-center pt-3">
              <Button
                variant="secondary"
                size="lg"
                loading={isLoadingMore}
                disabled={isLoadingMore}
                onClick={() => void setSize(size + 1)}
              >
                Carregar mais
              </Button>
            </div>
          )}
        </div>
      )}

      <AlertModalCore
        isOpen={!!deletingNoteId}
        handleClose={() => setDeletingNoteId(null)}
        handleSubmit={() => void handleDeleteNote()}
        isSubmitting={isDeleting}
        title="Excluir registro"
        content="Excluir este registro de contato da linha do tempo? Essa ação não pode ser desfeita."
        primaryButtonText={{ loading: "Excluindo", default: "Excluir" }}
        secondaryButtonText="Cancelar"
      />
    </section>
  );
}
