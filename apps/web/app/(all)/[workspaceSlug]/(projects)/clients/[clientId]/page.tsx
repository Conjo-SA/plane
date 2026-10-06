/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { ClientDetail } from "@/components/conjo-clients";
import { PageHead } from "@/components/core/page-title";
import type { Route } from "./+types/page";

export default function WorkspaceClientPage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Cliente" />
      <ClientDetail workspaceSlug={params.workspaceSlug} clientId={params.clientId} />
    </>
  );
}
