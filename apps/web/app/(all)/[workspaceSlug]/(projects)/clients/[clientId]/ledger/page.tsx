/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { ClientLedger } from "@/components/conjo-clients";
import { PageHead } from "@/components/core/page-title";
import type { Route } from "./+types/page";

export default function WorkspaceClientLedgerPage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Extrato de horas" />
      <ClientLedger workspaceSlug={params.workspaceSlug} clientId={params.clientId} />
    </>
  );
}
