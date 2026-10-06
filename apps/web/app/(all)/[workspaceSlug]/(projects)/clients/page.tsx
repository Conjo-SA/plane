/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { ClientsList } from "@/components/conjo-clients";
import { PageHead } from "@/components/core/page-title";
import type { Route } from "./+types/page";

export default function WorkspaceClientsPage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Clientes" />
      <ClientsList workspaceSlug={params.workspaceSlug} />
    </>
  );
}
