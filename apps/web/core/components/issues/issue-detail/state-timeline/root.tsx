/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import useSWR from "swr";
import { CheckCircle2, Timer } from "lucide-react";
// plane imports
import { Tooltip } from "@plane/propel/tooltip";
import type { TIssueStateSegment } from "@plane/types";
import { cn } from "@plane/utils";
// components
import { conjoBillingService } from "@/components/conjo-clients/helpers";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// local imports
import { formatDateTime, formatDuration, secondsSince, useNow } from "./helpers";

export const getIssueStateTimelineSWRKey = (issueId: string, stateId?: string | null) =>
  `ISSUE_STATE_TIMELINE_${issueId}_${stateId ?? ""}`;

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  className?: string;
};

/** Seconds of a segment; the current one keeps counting. */
const segmentSeconds = (segment: TIssueStateSegment, now: number) =>
  segment.seconds === null ? 0 : segment.ended_at ? segment.seconds : secondsSince(segment.started_at, now);

/** "Tempo por coluna": where the work item spent its time, in order, until done. */
export const IssueStateTimeline = observer(function IssueStateTimeline(props: Props) {
  const { workspaceSlug, projectId, issueId, className } = props;
  const now = useNow();
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const issue = getIssueById(issueId);
  // the key follows the card's state: moving the card (here or in real time) reloads the timeline
  const { data } = useSWR(
    workspaceSlug && projectId && issueId ? getIssueStateTimelineSWRKey(issueId, issue?.state_id) : null,
    () => conjoBillingService.getIssueStateTimeline(workspaceSlug, projectId, issueId),
    { revalidateOnFocus: true, keepPreviousData: true }
  );
  if (!data || data.segments.length === 0) return null;

  const timed = data.segments.filter((segment) => segment.seconds !== null);
  const final = data.is_done ? data.segments[data.segments.length - 1] : null;
  const totalSeconds = timed.reduce((sum, segment) => sum + segmentSeconds(segment, now), 0) || 1;
  const lead = data.is_done ? data.lead_seconds : secondsSince(data.created_at, now);

  // totals per column, the current one live
  const totals = new Map<string, { name: string; color: string; seconds: number; isCurrent: boolean }>();
  timed.forEach((segment) => {
    const key = segment.state_id ?? segment.name;
    const entry = totals.get(key) ?? { name: segment.name, color: segment.color, seconds: 0, isCurrent: false };
    entry.seconds += segmentSeconds(segment, now);
    if (!segment.ended_at) entry.isCurrent = true;
    totals.set(key, entry);
  });
  const ranking = sortBy([...totals.values()], (entry) => -entry.seconds);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-body-xs-medium text-secondary">Tempo por coluna</span>
        <span className="flex items-center gap-1 text-caption-sm-regular text-tertiary">
          {data.is_done ? (
            <CheckCircle2 className="size-3" strokeWidth={2} />
          ) : (
            <Timer className="size-3" strokeWidth={2} />
          )}
          {data.is_done
            ? `${final?.name ?? "Concluída"} em ${formatDuration(lead)}`
            : `Aberta há ${formatDuration(lead)}`}
        </span>
      </div>

      {/* chronological bar: each piece is one stay in a column */}
      <div className="flex h-2.5 w-full items-stretch gap-px overflow-hidden rounded-sm bg-layer-1">
        {timed.map((segment) => {
          const seconds = segmentSeconds(segment, now);
          const isCurrent = !segment.ended_at;
          return (
            <Tooltip
              key={`${segment.started_at}-${segment.state_id ?? segment.name}`}
              tooltipHeading={`${segment.name}: ${formatDuration(seconds)}`}
              tooltipContent={`${formatDateTime(segment.started_at)} → ${
                segment.ended_at ? formatDateTime(segment.ended_at) : "agora"
              }`}
            >
              <span
                className={cn("h-full min-w-1", isCurrent && "animate-pulse")}
                style={{ backgroundColor: segment.color, flexGrow: Math.max(seconds / totalSeconds, 0.005) }}
              />
            </Tooltip>
          );
        })}
        {final && (
          <Tooltip tooltipHeading={final.name} tooltipContent={formatDateTime(final.started_at)}>
            <span className="h-full w-1.5 flex-shrink-0" style={{ backgroundColor: final.color }} />
          </Tooltip>
        )}
      </div>

      {/* total per column */}
      <ul className="flex flex-col gap-1.5">
        {ranking.map((entry) => (
          <li key={entry.name} className="flex items-center gap-2 text-caption-sm-regular">
            <span className="size-2 flex-shrink-0 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className={cn("min-w-0 flex-1 truncate", entry.isCurrent ? "text-primary" : "text-secondary")}>
              {entry.name}
              {entry.isCurrent && <span className="text-tertiary"> · atual</span>}
            </span>
            <span className="text-tertiary tabular-nums">{Math.round((entry.seconds / totalSeconds) * 100)}%</span>
            <span className="w-16 text-right text-primary tabular-nums">{formatDuration(entry.seconds)}</span>
          </li>
        ))}
      </ul>

      {/* the path, step by step */}
      {data.segments.length > 1 && (
        <ol className="flex flex-col border-l border-subtle pl-3">
          {data.segments.map((segment) => (
            <li
              key={`${segment.started_at}-${segment.state_id ?? segment.name}`}
              className="relative py-1 text-caption-sm-regular"
            >
              <span
                className="absolute top-2 -left-[17px] size-2 rounded-full"
                style={{ backgroundColor: segment.color }}
              />
              <span className="text-secondary">{segment.name}</span>
              <span className="text-tertiary">
                {" · "}
                {formatDateTime(segment.started_at)}
                {segment.seconds !== null && ` · ${formatDuration(segmentSeconds(segment, now))}`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
});
