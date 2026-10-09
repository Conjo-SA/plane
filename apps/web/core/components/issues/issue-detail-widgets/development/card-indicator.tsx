/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { GitCommitHorizontal } from "lucide-react";
import useSWR from "swr";
// plane imports
import { Tooltip } from "@plane/propel/tooltip";
import { GitHubIntegrationService } from "@plane/services";
import { cn } from "@plane/utils";
// local imports
import { prStateMeta } from "./pr-state";

const githubIntegrationService = new GitHubIntegrationService();

/** One request per project, shared by every card through SWR's cache. */
export const useProjectDevelopmentSummary = (workspaceSlug: string | undefined, projectId: string | undefined) =>
  useSWR(
    workspaceSlug && projectId ? `PROJECT_DEVELOPMENT_SUMMARY_${projectId}` : null,
    () => githubIntegrationService.retrieveDevelopmentSummary(workspaceSlug!, projectId!),
    { revalidateOnFocus: true, dedupingInterval: 30_000 }
  );

type Props = {
  workspaceSlug: string | undefined;
  projectId: string | undefined;
  issueId: string;
};

/** Pull request state (or commit count) of a work item, shown on board and list cards. */
export function IssueDevelopmentCardIndicator(props: Props) {
  const { workspaceSlug, projectId, issueId } = props;
  const { data } = useProjectDevelopmentSummary(workspaceSlug, projectId);
  const item = data?.[issueId];
  if (!item || (item.pull_requests === 0 && item.commits === 0)) return null;

  const details = [
    item.pull_requests && `${item.pull_requests} PR${item.pull_requests > 1 ? "s" : ""}`,
    item.branches && `${item.branches} branch${item.branches > 1 ? "es" : ""}`,
    item.commits && `${item.commits} commit${item.commits > 1 ? "s" : ""}`,
  ]
    .filter(Boolean)
    .join(" · ");

  if (item.pr_state) {
    const meta = prStateMeta(item.pr_state);
    // Proposta A (canvas "Desenvolvimento Tasks"): o estado do PR e, ao lado, quantos commits.
    return (
      <Tooltip tooltipHeading="Desenvolvimento" tooltipContent={details} renderByDefault={false}>
        <span className="flex flex-shrink-0 items-center gap-1.5">
          <span
            className={cn(
              "flex h-5 flex-shrink-0 items-center gap-1 rounded-sm px-1.5 text-caption-sm-regular",
              meta.chip
            )}
          >
            <meta.Icon className="size-3 flex-shrink-0" strokeWidth={2.2} />
            PR {meta.label.toLowerCase()}
          </span>
          {item.commits > 0 && (
            <span className="flex-shrink-0 text-caption-sm-regular text-tertiary">
              {item.commits} commit{item.commits > 1 ? "s" : ""}
            </span>
          )}
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip tooltipHeading="Desenvolvimento" tooltipContent={details} renderByDefault={false}>
      <span className="flex h-5 flex-shrink-0 items-center gap-1 rounded-sm border-[0.5px] border-strong px-2 text-caption-sm-regular">
        <GitCommitHorizontal className="size-3 flex-shrink-0" strokeWidth={2} />
        {item.commits}
      </span>
    </Tooltip>
  );
}
