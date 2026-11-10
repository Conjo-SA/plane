/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
// plane imports
import { ConjoAreasService } from "@plane/services";
import type { TWorkspaceArea } from "@plane/types";

export const conjoAreasService = new ConjoAreasService();

export const getMyAreasSWRKey = (workspaceSlug: string) => `CONJO_MY_AREAS_${workspaceSlug}`;

/**
 * Conjo (MAN-467): areas the current user enters in the workspace. One request per workspace, shared through
 * SWR's cache by the sidebar, the routes and the work item widgets. While loading (or on error) nothing of an
 * area is shown: the API refuses it anyway.
 */
export const useWorkspaceAreas = (workspaceSlug: string | undefined) => {
  const { data, error, isLoading } = useSWR(
    workspaceSlug ? getMyAreasSWRKey(workspaceSlug) : null,
    workspaceSlug ? () => conjoAreasService.getMyAreas(workspaceSlug) : null,
    { revalidateOnFocus: true, dedupingInterval: 30_000 }
  );
  const areas = data?.areas;
  return {
    areas,
    isLoading: !!workspaceSlug && isLoading,
    hasError: !!error,
    hasArea: (area: TWorkspaceArea) => !!areas?.[area],
  };
};
