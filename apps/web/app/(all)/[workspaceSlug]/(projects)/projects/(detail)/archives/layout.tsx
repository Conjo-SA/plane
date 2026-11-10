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
import { ProjectsListMobileHeader } from "@/components/projects/mobile-header";
import { ProjectsBaseHeader } from "@/components/project/header";

export default function ProjectListLayout() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <AppHeader header={<ProjectsBaseHeader />} mobileHeader={<ProjectsListMobileHeader />} />
      <ContentWrapper>
        {/* Conjo (MAN-467): only for who enters the area */}
        <WorkspaceAreaGuard area="archives" workspaceSlug={workspaceSlug}>
          <Outlet />
        </WorkspaceAreaGuard>
      </ContentWrapper>
    </>
  );
}
