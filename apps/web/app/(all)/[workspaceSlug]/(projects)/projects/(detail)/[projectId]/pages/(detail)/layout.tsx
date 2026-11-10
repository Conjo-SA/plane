/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// component
import { Outlet } from "react-router";
import useSWR from "swr";
import { WorkspaceAreaGuard } from "@/components/conjo-areas";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
// plane web hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useWorkspaceAreas } from "@/hooks/use-workspace-areas";
// local components
import type { Route } from "./+types/layout";
import { PageDetailsHeader } from "./header";

export default function ProjectPageDetailsLayout({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { fetchPagesList } = usePageStore(EPageStoreType.PROJECT);
  const { hasArea } = useWorkspaceAreas(workspaceSlug);
  // fetching pages list (only for who enters the Docs area, MAN-467)
  useSWR(hasArea("docs") ? `PROJECT_PAGES_${projectId}` : null, () => fetchPagesList(workspaceSlug, projectId));
  return (
    <>
      <AppHeader header={<PageDetailsHeader />} />
      <ContentWrapper>
        <WorkspaceAreaGuard area="docs" workspaceSlug={workspaceSlug}>
          <Outlet />
        </WorkspaceAreaGuard>
      </ContentWrapper>
    </>
  );
}
