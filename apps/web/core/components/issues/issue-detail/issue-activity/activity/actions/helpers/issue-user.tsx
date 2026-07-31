/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";

type TIssueUser = {
  activityId: string;
  customUserName?: string;
};

export function IssueUser(props: TIssueUser) {
  const { activityId, customUserName } = props;
  // hooks
  const {
    activity: { getActivityById },
  } = useIssueDetail();

  const activity = getActivityById(activityId);

  if (!activity) return <></>;

  // Portal replies have no internal actor, so the requester identity comes from
  // the intake source. Without this the link would point at /profile/undefined.
  const hasActor = Boolean(activity.actor_detail?.id);
  const requesterName = activity.source_data?.extra?.requester_name || activity.source_data?.source_email;

  return (
    <>
      {customUserName || !hasActor ? (
        <span className="font-medium text-primary">{customUserName || requesterName || "Plane"}</span>
      ) : (
        <Link
          href={`/${activity?.workspace_detail?.slug}/profile/${activity?.actor_detail?.id}`}
          className="font-medium text-primary hover:underline"
        >
          {activity.actor_detail?.display_name}
        </Link>
      )}
    </>
  );
}
