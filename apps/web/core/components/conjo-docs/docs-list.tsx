/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { BookOpen, Earth, FileText, Search } from "lucide-react";
// plane imports
import { LockIcon } from "@plane/propel/icons";
import type { TWorkspaceDocPage } from "@plane/types";
import { CustomSelect, Input, Loader } from "@plane/ui";
import { getPageName, renderFormattedDate } from "@plane/utils";
// components
import { EmptyState, PageTitle } from "@/components/conjo-clients/common";
import { PageLabelChips } from "@/components/pages/labels";
// hooks
import { useLabel } from "@/hooks/store/use-label";
import { useProject } from "@/hooks/store/use-project";
import { useAppRouter } from "@/hooks/use-app-router";
// services
import { ProjectPageService } from "@/services/page";

const projectPageService = new ProjectPageService();

type TGroupBy = "project" | "tag";
type TGroup = { key: string; title: string; pages: TWorkspaceDocPage[] };

const NO_TAG = "__sem_etiqueta__";

type Props = { workspaceSlug: string };

/** Conjo: the workspace documentation, the pages of every project browsed by project and by tag. */
export const DocsList = observer(function DocsList({ workspaceSlug }: Props) {
  const router = useAppRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState("");
  // project, tag and grouping live in the URL so a filtered view can be shared
  const projectFilter = searchParams.get("projeto") ?? "";
  const tagFilter = (searchParams.get("tag") ?? "").toLowerCase();
  const groupBy: TGroupBy = searchParams.get("agrupar") === "tag" ? "tag" : "project";
  // store hooks
  const { fetchWorkspaceLabels, getLabelById } = useLabel();
  const { getProjectById } = useProject();

  const { data: pages, error } = useSWR(workspaceSlug ? `CONJO_DOCS_${workspaceSlug}` : null, () =>
    projectPageService.fetchWorkspacePages(workspaceSlug)
  );
  useSWR(workspaceSlug ? `WORKSPACE_LABELS_${workspaceSlug}` : null, () => fetchWorkspaceLabels(workspaceSlug), {
    revalidateOnFocus: false,
  });

  const setParam = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const search = params.toString();
    router.replace(`/${workspaceSlug}/docs${search ? `?${search}` : ""}`);
  };

  // a tag is a label name: the same name in different projects is the same tag
  const tagNames = (page: TWorkspaceDocPage) =>
    Array.from(new Set(page.label_ids.map((id) => getLabelById(id)?.name).filter((name): name is string => !!name)));

  const projectOptions = useMemo(() => {
    const ids = new Set((pages ?? []).flatMap((page) => page.project_ids));
    const projects = Array.from(ids)
      .map((id) => getProjectById(id))
      .filter((project) => !!project);
    return sortBy(projects, (project) => project.name.toLowerCase());
  }, [pages, getProjectById]);

  const tagOptions = useMemo(() => {
    const names = new Map<string, string>();
    (pages ?? []).forEach((page) => tagNames(page).forEach((name) => names.set(name.toLowerCase(), name)));
    return sortBy(Array.from(names.entries()), ([key]) => key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, getLabelById]);

  const visiblePages = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (pages ?? []).filter(
      (page) =>
        (!term || getPageName(page.name).toLowerCase().includes(term)) &&
        (!projectFilter || page.project_ids.includes(projectFilter)) &&
        (!tagFilter || tagNames(page).some((name) => name.toLowerCase() === tagFilter))
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, query, projectFilter, tagFilter, getLabelById]);

  const groups = useMemo<TGroup[]>(() => {
    const map = new Map<string, TGroup>();
    const add = (key: string, title: string, page: TWorkspaceDocPage) => {
      if (!map.has(key)) map.set(key, { key, title, pages: [] });
      map.get(key)?.pages.push(page);
    };
    visiblePages.forEach((page) => {
      if (groupBy === "project") {
        page.project_ids.forEach((id) => add(id, getProjectById(id)?.name ?? "Projeto", page));
      } else {
        const names = tagNames(page);
        if (names.length === 0) add(NO_TAG, "Sem etiqueta", page);
        names.forEach((name) => add(name.toLowerCase(), name, page));
      }
    });
    // "Sem etiqueta" goes last
    return sortBy(Array.from(map.values()), [(group) => group.key === NO_TAG, (group) => group.title.toLowerCase()]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visiblePages, groupBy, getProjectById, getLabelById]);

  const selectedProject = projectFilter ? getProjectById(projectFilter) : undefined;
  const selectedTag = tagOptions.find(([key]) => key === tagFilter)?.[1];

  return (
    <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
      <PageTitle
        title="Documentação"
        subtitle="Páginas de todos os projetos em que você participa, por projeto ou por etiqueta (cliente/sistema)."
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-[1_1_240px] sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-tertiary" />
          <Input
            aria-label="Buscar página"
            placeholder="Buscar pelo título"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full pl-8"
          />
        </div>
        <CustomSelect
          value={projectFilter}
          label={selectedProject ? `Projeto: ${selectedProject.name}` : "Todos os projetos"}
          onChange={(value: string) => setParam("projeto", value)}
          maxHeight="md"
        >
          <CustomSelect.Option value="">Todos os projetos</CustomSelect.Option>
          {projectOptions.map((project) => (
            <CustomSelect.Option key={project.id} value={project.id}>
              {project.name}
            </CustomSelect.Option>
          ))}
        </CustomSelect>
        <CustomSelect
          value={tagFilter}
          label={selectedTag ? `Etiqueta: ${selectedTag}` : "Todas as etiquetas"}
          onChange={(value: string) => setParam("tag", value)}
          maxHeight="md"
        >
          <CustomSelect.Option value="">Todas as etiquetas</CustomSelect.Option>
          {tagOptions.map(([key, name]) => (
            <CustomSelect.Option key={key} value={key}>
              {name}
            </CustomSelect.Option>
          ))}
        </CustomSelect>
        <CustomSelect
          value={groupBy}
          label={groupBy === "tag" ? "Agrupar por etiqueta" : "Agrupar por projeto"}
          onChange={(value: TGroupBy) => setParam("agrupar", value === "tag" ? "tag" : "")}
        >
          <CustomSelect.Option value="project">Agrupar por projeto</CustomSelect.Option>
          <CustomSelect.Option value="tag">Agrupar por etiqueta</CustomSelect.Option>
        </CustomSelect>
      </div>

      {error ? (
        <EmptyState title="Não foi possível carregar a documentação" description="Tente de novo em instantes." />
      ) : !pages ? (
        <Loader className="flex flex-col gap-2">
          <Loader.Item height="48px" />
          <Loader.Item height="48px" />
          <Loader.Item height="48px" />
        </Loader>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="size-6" />}
          title="Nenhuma página encontrada"
          description="Crie páginas nos projetos e marque-as com etiquetas para encontrá-las aqui."
        />
      ) : (
        groups.map((group) => (
          <section key={group.key} className="flex flex-col gap-2">
            <h2 className="text-13 font-medium text-secondary">
              {group.title} <span className="text-tertiary">· {group.pages.length}</span>
            </h2>
            <ul className="flex flex-col overflow-hidden rounded-lg border border-subtle bg-layer-1">
              {group.pages.map((page) => {
                // inside a project group the link opens the page in that project
                const projectId =
                  groupBy === "project"
                    ? group.key
                    : (page.project_ids.find((id) => id === projectFilter) ?? page.project_ids[0]);
                return (
                  <li
                    key={`${group.key}-${page.id}`}
                    className="flex flex-wrap items-center gap-3 border-b border-subtle px-4 py-3 last:border-b-0 hover:bg-layer-1-hover"
                  >
                    <Link
                      href={`/${workspaceSlug}/projects/${projectId}/pages/${page.id}`}
                      className="flex min-w-0 flex-1 items-center gap-3"
                    >
                      <FileText className="size-4 flex-shrink-0 text-tertiary" />
                      <span className="truncate text-13 text-primary">{getPageName(page.name)}</span>
                    </Link>
                    <PageLabelChips labelIds={page.label_ids} onClick={(name) => setParam("tag", name.toLowerCase())} />
                    {groupBy === "tag" &&
                      page.project_ids.map((id) => (
                        <span key={id} className="text-11 text-tertiary">
                          {getProjectById(id)?.identifier}
                        </span>
                      ))}
                    <span className="text-tertiary">
                      {page.access === 0 ? <Earth className="size-3.5" /> : <LockIcon className="size-3.5" />}
                    </span>
                    <span className="w-24 text-right text-11 text-tertiary">
                      {renderFormattedDate(page.updated_at)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </div>
  );
});
