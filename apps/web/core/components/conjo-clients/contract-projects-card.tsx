/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClient, TClientLabel, TClientLabelOption } from "@plane/types";
import { Checkbox, EModalWidth, Input } from "@plane/ui";
// hooks
import { useProject } from "@/hooks/store/use-project";
// local imports
import { Card, FormModal } from "./common";
import {
  clientLabelOptionsKey,
  clientsKey,
  conjoBillingService,
  formatHours,
  formatMonthYear,
  getErrorMessage,
} from "./helpers";

type Props = {
  workspaceSlug: string;
  client: TClient;
  isAdmin: boolean;
  onChanged: () => Promise<unknown>;
};

export function ContractProjectsCard({ workspaceSlug, client, isAdmin, onChanged }: Props) {
  const [isProjectsOpen, setIsProjectsOpen] = useState(false);
  const [isLabelsOpen, setIsLabelsOpen] = useState(false);
  const base = `/${workspaceSlug}/clients/${client.id}`;
  const activeContract = client.contracts.find((contract) => contract.is_active);
  const pastContracts = client.contracts.filter((contract) => !contract.is_active);

  return (
    <Card title="Contrato e projetos">
      {activeContract ? (
        <Link
          href={`${base}/contract/${activeContract.id}`}
          className="flex items-center justify-between gap-2 rounded-md border border-subtle px-3 py-2.5 text-13 hover:bg-layer-1-hover"
        >
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-primary">{activeContract.name}</span>
            <span className="text-12 text-tertiary">
              {formatHours(activeContract.hours_per_month)}/mês · dia {activeContract.credit_day}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-1 text-12 text-tertiary">
            desde {formatMonthYear(activeContract.starts_on)}
            <ChevronRight className="size-3.5" aria-hidden />
          </span>
        </Link>
      ) : (
        <div className="flex flex-col gap-2 rounded-md border border-dashed border-subtle px-3 py-3 text-13">
          <span className="text-secondary">Nenhum contrato ativo.</span>
          {isAdmin && (
            <Link href={`${base}/contract`} className="font-medium text-accent-primary hover:underline">
              Criar contrato de pacote de horas
            </Link>
          )}
        </div>
      )}
      {activeContract && isAdmin && (
        <Link href={`${base}/contract`} className="text-12 text-accent-primary hover:underline">
          Novo contrato (substitui o atual)
        </Link>
      )}
      {pastContracts.length > 0 && (
        <details className="text-12">
          <summary className="cursor-pointer text-tertiary">Contratos anteriores ({pastContracts.length})</summary>
          <ul className="mt-1.5 flex flex-col gap-1">
            {pastContracts.map((contract) => (
              <li key={contract.id}>
                <Link href={`${base}/contract/${contract.id}`} className="text-secondary hover:underline">
                  {contract.name} · {formatMonthYear(contract.starts_on)}
                  {contract.ends_on ? ` a ${formatMonthYear(contract.ends_on)}` : ""}
                </Link>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <h3 className="text-12 font-medium text-secondary">Projetos</h3>
        {isAdmin && (
          <button
            type="button"
            className="text-13 font-medium text-accent-primary hover:underline"
            onClick={() => setIsProjectsOpen(true)}
          >
            {client.projects.length ? "Alterar" : "Vincular"}
          </button>
        )}
      </div>
      {client.projects.length === 0 ? (
        <p className="text-12 text-tertiary">
          Nenhum projeto vinculado. As tarefas dos projetos vinculados contam no pacote deste cliente.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {client.projects.map((project) => (
            <Link
              key={project.id}
              href={`/${workspaceSlug}/projects/${project.id}/issues`}
              className="rounded-sm bg-layer-2 px-2 py-0.5 text-12 text-primary hover:bg-layer-2-hover"
            >
              {project.identifier} · {project.name}
            </Link>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <h3 className="text-12 font-medium text-secondary">Etiqueta no board</h3>
        {isAdmin && (
          <button
            type="button"
            className="text-13 font-medium text-accent-primary hover:underline"
            onClick={() => setIsLabelsOpen(true)}
          >
            {client.labels.length ? "Alterar" : "Vincular"}
          </button>
        )}
      </div>
      <p className="text-12 text-tertiary">
        Opcional. Mantém a etiqueta usada no board e no link do portal: ao escolher este cliente num card, a etiqueta é
        aplicada; um pedido pelo link com a etiqueta já chega com o cliente.
      </p>
      {client.labels.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {client.labels.map((label) => (
            <LabelChip key={label.id} label={label} />
          ))}
        </div>
      )}

      <ProjectsModal
        isOpen={isProjectsOpen}
        workspaceSlug={workspaceSlug}
        client={client}
        onClose={() => setIsProjectsOpen(false)}
        onSaved={onChanged}
      />
      <LabelsModal
        isOpen={isLabelsOpen}
        workspaceSlug={workspaceSlug}
        client={client}
        onClose={() => setIsLabelsOpen(false)}
        onSaved={onChanged}
      />
    </Card>
  );
}

const ProjectsModal = observer(function ProjectsModal(props: {
  isOpen: boolean;
  workspaceSlug: string;
  client: TClient;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const { isOpen, workspaceSlug, client, onClose, onSaved } = props;
  const { workspaceProjectIds, getPartialProjectById } = useProject();
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // The clients list tells which projects already belong to another client (a project has one client).
  const { data: clients } = useSWR(isOpen ? clientsKey(workspaceSlug) : null, () =>
    conjoBillingService.listClients(workspaceSlug)
  );
  const ownerByProject = useMemo(() => {
    const owners = new Map<string, string>();
    for (const other of clients ?? []) {
      if (other.id === client.id) continue;
      for (const projectId of other.project_ids) owners.set(projectId, other.name);
    }
    return owners;
  }, [clients, client.id]);

  useEffect(() => {
    if (isOpen) {
      setSelected(client.projects.map((project) => project.id));
      setQuery("");
    }
  }, [isOpen, client.projects]);

  const projects = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (
      (workspaceProjectIds ?? [])
        .map((id) => getPartialProjectById(id))
        .filter((project) => !!project)
        .filter(
          (project) =>
            !term || project.name.toLowerCase().includes(term) || project.identifier.toLowerCase().includes(term)
        )
        // a fresh array from filter(), safe to sort in place
        // oxlint-disable-next-line unicorn/no-array-sort
        .sort((a, b) => a.name.localeCompare(b.name, "pt-BR"))
    );
  }, [workspaceProjectIds, getPartialProjectById, query]);

  const toggle = (projectId: string) =>
    setSelected((current) =>
      current.includes(projectId) ? current.filter((id) => id !== projectId) : [...current, projectId]
    );

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await conjoBillingService.setClientProjects(workspaceSlug, client.id, selected);
      await onSaved();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível salvar os projetos do cliente."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title="Projetos do cliente"
      description="As tarefas dos projetos marcados contam no pacote deste cliente. Cada projeto pertence a um cliente só."
      submitLabel="Salvar projetos"
      isSubmitting={isSubmitting}
      width={EModalWidth.LG}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-tertiary" />
        <Input
          aria-label="Buscar projeto"
          placeholder="Buscar projeto"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full pl-8"
        />
      </div>
      <ul className="flex max-h-80 flex-col overflow-y-auto rounded-md border border-subtle">
        {projects.length === 0 && <li className="px-3 py-4 text-center text-12 text-tertiary">Nenhum projeto.</li>}
        {projects.map((project) => {
          const owner = ownerByProject.get(project.id);
          const inputId = `client-project-${project.id}`;
          return (
            <li key={project.id} className="border-b border-subtle last:border-b-0">
              <label
                htmlFor={inputId}
                className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-13 hover:bg-layer-1-hover"
              >
                <Checkbox
                  id={inputId}
                  checked={selected.includes(project.id)}
                  onChange={() => toggle(project.id)}
                  disabled={!!owner}
                />
                <span className="flex min-w-0 flex-1 items-center gap-2">
                  <span className="shrink-0 text-12 font-medium text-tertiary">{project.identifier}</span>
                  <span className="truncate text-primary">{project.name}</span>
                </span>
                {owner && <span className="shrink-0 text-11 text-tertiary">de {owner}</span>}
              </label>
            </li>
          );
        })}
      </ul>
      <span className="text-12 text-tertiary">
        {selected.length === 1 ? "1 projeto selecionado" : `${selected.length} projetos selecionados`}
      </span>
    </FormModal>
  );
});

function LabelDot({ color }: { color: string }) {
  return (
    <span
      className="size-2 shrink-0 rounded-full bg-layer-3"
      style={color ? { backgroundColor: color } : undefined}
      aria-hidden
    />
  );
}

function LabelChip({ label }: { label: TClientLabel }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-sm bg-layer-2 px-2 py-0.5 text-12 text-primary">
      <LabelDot color={label.color} />
      {label.name} · {label.project_identifier}
    </span>
  );
}

type TLabelGroup = { projectId: string; identifier: string; name: string; labels: TClientLabelOption[] };

function LabelsModal(props: {
  isOpen: boolean;
  workspaceSlug: string;
  client: TClient;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const { isOpen, workspaceSlug, client, onClose, onSaved } = props;
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data, error, mutate } = useSWR(isOpen ? clientLabelOptionsKey(workspaceSlug) : null, () =>
    conjoBillingService.getClientLabelOptions(workspaceSlug)
  );

  useEffect(() => {
    if (isOpen) {
      setSelected(client.labels.map((label) => label.id));
      setQuery("");
    }
  }, [isOpen, client.labels]);

  // Labels grouped by project, projects and labels in alphabetical order.
  const groups = useMemo(() => {
    const term = query.trim().toLowerCase();
    const byProject = new Map<string, TLabelGroup>();
    for (const label of data?.labels ?? []) {
      if (
        term &&
        !label.name.toLowerCase().includes(term) &&
        !label.project_identifier.toLowerCase().includes(term) &&
        !label.project_name.toLowerCase().includes(term)
      )
        continue;
      const group = byProject.get(label.project_id) ?? {
        projectId: label.project_id,
        identifier: label.project_identifier,
        name: label.project_name,
        labels: [],
      };
      group.labels.push(label);
      byProject.set(label.project_id, group);
    }
    const result = [...byProject.values()];
    for (const group of result) {
      // fresh arrays built above, safe to sort in place
      // oxlint-disable-next-line unicorn/no-array-sort
      group.labels.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
    }
    // oxlint-disable-next-line unicorn/no-array-sort
    return result.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
  }, [data, query]);

  const toggle = (labelId: string) =>
    setSelected((current) =>
      current.includes(labelId) ? current.filter((id) => id !== labelId) : [...current, labelId]
    );

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await conjoBillingService.setClientLabels(workspaceSlug, client.id, selected);
      await onSaved();
      void mutate();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível salvar as etiquetas do cliente."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title="Etiqueta no board"
      description="Aplicada ao escolher este cliente num card; pedidos pelo link do portal com ela já chegam com o cliente. Cada etiqueta pertence a um cliente só."
      submitLabel="Salvar etiquetas"
      isSubmitting={isSubmitting}
      submitDisabled={!data}
      width={EModalWidth.LG}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-tertiary" />
        <Input
          aria-label="Buscar etiqueta"
          placeholder="Buscar etiqueta ou projeto"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full pl-8"
        />
      </div>
      <div className="flex max-h-80 flex-col overflow-y-auto rounded-md border border-subtle">
        {!data ? (
          <p className="px-3 py-4 text-center text-12 text-tertiary">
            {error ? getErrorMessage(error, "Não foi possível carregar as etiquetas.") : "Carregando etiquetas..."}
          </p>
        ) : groups.length === 0 ? (
          <p className="px-3 py-4 text-center text-12 text-tertiary">Nenhuma etiqueta.</p>
        ) : (
          groups.map((group) => (
            <section key={group.projectId} className="border-b border-subtle last:border-b-0">
              <h4 className="flex items-center gap-2 bg-layer-2 px-3 py-1.5 text-12">
                <span className="shrink-0 font-medium text-tertiary">{group.identifier}</span>
                <span className="truncate text-secondary">{group.name}</span>
              </h4>
              <ul className="flex flex-col">
                {group.labels.map((label) => {
                  const owner = label.client && label.client.id !== client.id ? label.client.name : null;
                  const inputId = `client-label-${label.id}`;
                  return (
                    <li key={label.id} className="border-t border-subtle">
                      <label
                        htmlFor={inputId}
                        className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-13 hover:bg-layer-1-hover"
                      >
                        <Checkbox
                          id={inputId}
                          checked={selected.includes(label.id)}
                          onChange={() => toggle(label.id)}
                          disabled={!!owner}
                        />
                        <span className="flex min-w-0 flex-1 items-center gap-2">
                          <LabelDot color={label.color} />
                          <span className="truncate text-primary">{label.name}</span>
                        </span>
                        {owner && <span className="shrink-0 text-11 text-tertiary">de {owner}</span>}
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>
      <span className="text-12 text-tertiary">
        {selected.length === 1 ? "1 etiqueta selecionada" : `${selected.length} etiquetas selecionadas`}
      </span>
    </FormModal>
  );
}
