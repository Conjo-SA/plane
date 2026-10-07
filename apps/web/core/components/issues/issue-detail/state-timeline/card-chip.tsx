/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { CheckCircle2, Timer } from "lucide-react";
// plane imports
import { Tooltip } from "@plane/propel/tooltip";
import type { TIssue } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
// local imports
import { formatDuration, secondsSince, useNow } from "./helpers";

const STALE_AFTER_SECONDS = 7 * 24 * 60 * 60;

type Props = { issue: TIssue };

/** Card counter: time in the current column, or the total time until it was done. */
export const IssueStateTimeCardChip = observer(function IssueStateTimeCardChip(props: Props) {
  const { issue } = props;
  const now = useNow();
  const { getStateById } = useProjectState();
  const state = getStateById(issue.state_id);
  if (!state || !issue.created_at) return null;

  const isDone = state.group === "completed" || state.group === "cancelled";
  const since = issue.state_changed_at ?? issue.created_at;

  if (isDone) {
    const lead = (new Date(since).getTime() - new Date(issue.created_at).getTime()) / 1000;
    return (
      <Tooltip
        tooltipHeading={`${state.name} em ${formatDuration(lead)}`}
        tooltipContent="Tempo da criação até chegar nesta coluna"
        renderByDefault={false}
      >
        <span className="flex h-5 flex-shrink-0 items-center gap-1 rounded-sm border-[0.5px] border-strong px-2 text-caption-sm-regular text-tertiary">
          <CheckCircle2 className="size-3 flex-shrink-0" strokeWidth={2} />
          {formatDuration(lead)}
        </span>
      </Tooltip>
    );
  }

  const inState = secondsSince(since, now);
  const total = secondsSince(issue.created_at, now);
  const isStale = inState >= STALE_AFTER_SECONDS;

  return (
    <Tooltip
      tooltipHeading={`Há ${formatDuration(inState)} em ${state.name}`}
      tooltipContent={`Aberta há ${formatDuration(total)}`}
      renderByDefault={false}
    >
      <span
        className={cn(
          "flex h-5 flex-shrink-0 items-center gap-1 rounded-sm border-[0.5px] border-strong px-2 text-caption-sm-regular",
          isStale && "border-amber-500/60 text-amber-600 dark:text-amber-400"
        )}
      >
        <Timer className="size-3 flex-shrink-0" strokeWidth={2} />
        {formatDuration(inState)}
      </span>
    </Tooltip>
  );
});
