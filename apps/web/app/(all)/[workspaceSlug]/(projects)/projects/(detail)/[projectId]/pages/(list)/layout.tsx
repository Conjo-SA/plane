/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { Outlet, useParams } from "react-router";
import { WorkspaceAreaGuard } from "@/components/conjo-areas";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
// local components
import { PagesListHeader } from "./header";

export default function ProjectPagesListLayout() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <AppHeader header={<PagesListHeader />} />
      <ContentWrapper>
        {/* Conjo (MAN-467): only for who enters the area */}
        <WorkspaceAreaGuard area="docs" workspaceSlug={workspaceSlug}>
          <Outlet />
        </WorkspaceAreaGuard>
      </ContentWrapper>
    </>
  );
}
