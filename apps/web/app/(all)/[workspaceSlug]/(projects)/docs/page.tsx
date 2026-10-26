/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { DocsList } from "@/components/conjo-docs";
import { PageHead } from "@/components/core/page-title";
import type { Route } from "./+types/page";

export default function WorkspaceDocsPage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Documentação" />
      <DocsList workspaceSlug={params.workspaceSlug} />
    </>
  );
}
