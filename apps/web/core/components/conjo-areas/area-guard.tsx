/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { Lock } from "lucide-react";
// plane imports
import type { TWorkspaceArea } from "@plane/types";
import { Loader } from "@plane/ui";
// hooks
import { useWorkspaceAreas } from "@/hooks/use-workspace-areas";

export const AREA_LABELS: Record<TWorkspaceArea, string> = {
  clients: "Clientes",
  docs: "Documentação",
  time: "Horas e orçamento",
  integrations: "Integrações",
  archives: "Arquivos",
};

type NoAccessProps = { area: TWorkspaceArea };

/** Shown instead of an area the user does not enter (opened by a direct link, for instance). */
export function WorkspaceAreaNoAccess({ area }: NoAccessProps) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-8 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-layer-1">
        <Lock className="size-5 text-tertiary" />
      </span>
      <h2 className="text-16 font-medium text-primary">Sem acesso a {AREA_LABELS[area]}</h2>
      <p className="max-w-md text-13 text-secondary">
        Esta área não está liberada para você neste workspace. Se precisar dela, peça a um administrador do workspace.
      </p>
    </div>
  );
}

type GuardProps = {
  area: TWorkspaceArea;
  workspaceSlug: string | undefined;
  children: ReactNode;
};

/** Renders the area only for who enters it; the API refuses it too. */
export function WorkspaceAreaGuard({ area, workspaceSlug, children }: GuardProps) {
  const { areas, isLoading, hasArea } = useWorkspaceAreas(workspaceSlug);
  if (isLoading && !areas)
    return (
      <Loader className="space-y-3 p-6">
        <Loader.Item height="32px" />
        <Loader.Item height="120px" />
      </Loader>
    );
  if (!hasArea(area)) return <WorkspaceAreaNoAccess area={area} />;
  return <>{children}</>;
}
