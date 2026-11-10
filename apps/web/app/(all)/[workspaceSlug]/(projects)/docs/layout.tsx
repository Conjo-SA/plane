/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Outlet, useParams } from "react-router";
import { WorkspaceAreaGuard } from "@/components/conjo-areas";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
// local imports
import { WorkspaceDocsHeader } from "./header";

export default function WorkspaceDocsLayout() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <AppHeader header={<WorkspaceDocsHeader />} />
      <ContentWrapper>
        {/* Conjo (MAN-467): only for who enters the area */}
        <WorkspaceAreaGuard area="docs" workspaceSlug={workspaceSlug}>
          <Outlet />
        </WorkspaceAreaGuard>
      </ContentWrapper>
    </>
  );
}
