/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Building2 } from "lucide-react";
import useSWR from "swr";
// plane imports
import { Tooltip } from "@plane/propel/tooltip";
// components
import { conjoBillingService } from "@/components/conjo-clients/helpers";

export const getProjectClientSummarySWRKey = (projectId: string) => `PROJECT_CLIENT_SUMMARY_${projectId}`;

/** One request per project, shared by every card through SWR's cache. */
export const useProjectClientSummary = (workspaceSlug: string | undefined, projectId: string | undefined) =>
  useSWR(
    workspaceSlug && projectId ? getProjectClientSummarySWRKey(projectId) : null,
    () => conjoBillingService.getProjectClientSummary(workspaceSlug!, projectId!),
    { revalidateOnFocus: true, dedupingInterval: 30_000 }
  );

type Props = {
  workspaceSlug: string | undefined;
  projectId: string | undefined;
  issueId: string;
};

/** Client chosen on the card, shown on board and list cards (clients inherited from the project are not shown). */
export function IssueClientCardChip(props: Props) {
  const { workspaceSlug, projectId, issueId } = props;
  const { data } = useProjectClientSummary(workspaceSlug, projectId);
  const client = data?.issues?.[issueId];
  if (!client) return null;

  return (
    <Tooltip tooltipHeading="Cliente" tooltipContent={client.name} renderByDefault={false}>
      <span className="flex h-5 flex-shrink-0 items-center gap-1 rounded-sm border-[0.5px] border-strong px-2 text-caption-sm-regular">
        <Building2 className="size-3 flex-shrink-0" strokeWidth={2} />
        <span className="max-w-[16ch] truncate">{client.name}</span>
      </span>
    </Tooltip>
  );
}
