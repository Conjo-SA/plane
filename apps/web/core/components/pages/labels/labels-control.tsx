/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Tag } from "lucide-react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { CustomSearchSelect } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useLabel } from "@/hooks/store/use-label";
import { useProject } from "@/hooks/store/use-project";
// services
import { ProjectPageService } from "@/services/page";
// store
import type { TPageInstance } from "@/store/pages/base-page";
// local imports
import { PageLabelChips } from "./label-chips";

const projectPageService = new ProjectPageService();

type Props = {
  page: TPageInstance;
  className?: string;
};

/** Conjo: tags of a page, picked from the labels of every project of the workspace the user is in. */
export const PageLabelsControl = observer(function PageLabelsControl(props: Props) {
  const { page, className } = props;
  const { workspaceSlug, projectId: routerProjectId } = useParams();
  const slug = workspaceSlug?.toString() ?? "";
  const projectId = routerProjectId?.toString() ?? page.project_ids?.[0];
  // store hooks
  const { fetchWorkspaceLabels, getWorkspaceLabels } = useLabel();
  const { getProjectIdentifierById } = useProject();
  useSWR(slug ? `WORKSPACE_LABELS_${slug}` : null, () => fetchWorkspaceLabels(slug), {
    revalidateOnFocus: false,
  });
  const labels = getWorkspaceLabels(slug);
  const value = page.label_ids ?? [];
  const canEdit = page.isContentEditable;

  const options = useMemo(
    () =>
      (labels ?? []).map((label) => {
        const identifier = label.project_id ? getProjectIdentifierById(label.project_id) : "";
        return {
          value: label.id,
          query: `${label.name} ${identifier}`,
          content: (
            <div className="flex items-center gap-2 truncate">
              <span className="size-2 flex-shrink-0 rounded-full" style={{ backgroundColor: label.color }} />
              <span className="truncate">{label.name}</span>
              {identifier && <span className="text-11 text-tertiary">{identifier}</span>}
            </div>
          ),
        };
      }),
    [labels, getProjectIdentifierById]
  );

  const handleChange = async (labelIds: string[]) => {
    if (!page.id || !projectId) return;
    const previous = page.label_ids;
    page.mutateProperties({ label_ids: labelIds });
    try {
      await projectPageService.updateLabels(slug, projectId, page.id, labelIds);
    } catch {
      page.mutateProperties({ label_ids: previous });
      setToast({ type: TOAST_TYPE.ERROR, title: "Erro", message: "Não foi possível alterar as etiquetas da página." });
    }
  };

  const chips = <PageLabelChips labelIds={value} emptyLabel={canEdit ? "Etiquetas" : undefined} />;

  if (!canEdit) return value.length > 0 ? <div className={className}>{chips}</div> : null;

  return (
    // inside a list row the click would also open the page
    <div
      role="presentation"
      className={cn("flex items-center", className)}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <CustomSearchSelect
        value={value}
        onChange={handleChange}
        options={options}
        multiple
        noChevron
        customButton={
          <span className="flex items-center gap-1 text-tertiary hover:text-secondary">
            <Tag className="size-3.5 flex-shrink-0" />
            {chips}
          </span>
        }
        noResultsMessage="Nenhuma etiqueta encontrada"
      />
    </div>
  );
});
