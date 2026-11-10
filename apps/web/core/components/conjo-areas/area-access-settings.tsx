/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { Trash2 } from "lucide-react";
import useSWR, { mutate as globalMutate } from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type {
  TWorkspaceArea,
  TWorkspaceAreaConfiguration,
  TWorkspaceAreaOverride,
  TWorkspaceAreaRole,
  TWorkspaceAreaRule,
} from "@plane/types";
import { EUserWorkspaceRoles } from "@plane/types";
import { Checkbox, CustomSearchSelect, CustomSelect, Loader } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { conjoAreasService, getMyAreasSWRKey } from "@/hooks/use-workspace-areas";
// local imports
import { AREA_LABELS } from "./area-guard";

const configurationKey = (workspaceSlug: string) => `CONJO_AREA_ACCESS_${workspaceSlug}`;

const AREA_DESCRIPTIONS: Record<TWorkspaceArea, string> = {
  clients: "Cadastro, contatos, contratos, extrato, relatório e timeline dos clientes, e o cliente de cada item.",
  docs: "Tela de Documentação e páginas dos projetos, incluindo a Wiki.",
  time: "Horas lançadas, tipo do trabalho e orçamento de horas no item.",
  integrations: "Configuração do GitHub e do Conjo Chat nos projetos.",
  archives: "Itens, ciclos, módulos e projetos arquivados.",
};

const ROLE_COLUMNS: { role: TWorkspaceAreaRole; label: string }[] = [
  { role: 15, label: "Membro" },
  { role: 5, label: "Convidado" },
];

const ROLE_NAMES: Record<number, string> = { 20: "Administrador", 15: "Membro", 5: "Convidado" };

const errorMessage = (err: unknown, fallback: string): string =>
  (err as { data?: { error?: string } } | undefined)?.data?.error || fallback;

type Props = { workspaceSlug: string };

/** Conjo (MAN-467): who enters each area of the workspace, with per-person exceptions. Admins only. */
export const WorkspaceAreaAccessSettings = observer(function WorkspaceAreaAccessSettings({ workspaceSlug }: Props) {
  const [saving, setSaving] = useState<string | null>(null);
  const { data, mutate } = useSWR(configurationKey(workspaceSlug), () =>
    conjoAreasService.getConfiguration(workspaceSlug)
  );

  const apply = async (key: string, request: () => Promise<TWorkspaceAreaConfiguration>, success: string) => {
    setSaving(key);
    try {
      await mutate(await request(), { revalidate: false });
      void globalMutate(getMyAreasSWRKey(workspaceSlug));
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Permissões salvas", message: success });
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro",
        message: errorMessage(err, "Não foi possível salvar as permissões."),
      });
    } finally {
      setSaving(null);
    }
  };

  const toggleRole = (rule: TWorkspaceAreaRule, role: TWorkspaceAreaRole) => {
    const roles = rule.allowed_roles.includes(role)
      ? rule.allowed_roles.filter((value) => value !== role)
      : [...rule.allowed_roles, role];
    void apply(
      `${rule.key}-${role}`,
      () => conjoAreasService.updateRoles(workspaceSlug, { [rule.key]: roles }),
      `${AREA_LABELS[rule.key]}: ${ROLE_NAMES[role]} ${roles.includes(role) ? "passa a acessar" : "deixa de acessar"}.`
    );
  };

  if (!data)
    return (
      <Loader className="space-y-3">
        <Loader.Item height="48px" />
        <Loader.Item height="48px" />
        <Loader.Item height="48px" />
      </Loader>
    );

  return (
    <div className="flex flex-col gap-8">
      <p className="text-13 text-secondary">
        Administradores do workspace sempre acessam todas as áreas. A área é um portão a mais: ela não dá a ninguém o
        que o papel já não permite (por exemplo, só administradores alteram clientes) e cada pessoa continua vendo só os
        projetos de que participa.
      </p>

      <section className="flex flex-col">
        <div className="grid grid-cols-[minmax(0,1fr)_96px_96px] items-center gap-3 border-b border-subtle pb-2 text-12 font-medium text-tertiary">
          <span>Área</span>
          {ROLE_COLUMNS.map((column) => (
            <span key={column.role} className="text-center">
              {column.label}
            </span>
          ))}
        </div>
        {data.areas.map((rule) => (
          <div
            key={rule.key}
            className="grid grid-cols-[minmax(0,1fr)_96px_96px] items-center gap-3 border-b border-subtle py-3"
          >
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="flex items-center gap-2 text-13 font-medium text-primary">
                {AREA_LABELS[rule.key]}
                {rule.is_default && (
                  <span className="font-normal rounded-sm bg-layer-1 px-1.5 py-0.5 text-11 text-tertiary">padrão</span>
                )}
              </span>
              <span className="text-12 text-tertiary">{AREA_DESCRIPTIONS[rule.key]}</span>
            </div>
            {ROLE_COLUMNS.map((column) => {
              const id = `area-${rule.key}-${column.role}`;
              return (
                <label key={column.role} htmlFor={id} className="flex cursor-pointer justify-center">
                  <span className="sr-only">
                    {column.label} acessa {AREA_LABELS[rule.key]}
                  </span>
                  <Checkbox
                    id={id}
                    checked={rule.allowed_roles.includes(column.role)}
                    disabled={saving !== null}
                    onChange={() => toggleRole(rule, column.role)}
                  />
                </label>
              );
            })}
          </div>
        ))}
      </section>

      <OverridesSection
        workspaceSlug={workspaceSlug}
        overrides={data.overrides}
        saving={saving}
        onSave={(area, memberId, allow, name) =>
          void apply(
            `override-${area}-${memberId}`,
            () => conjoAreasService.saveOverride(workspaceSlug, { area, member_id: memberId, allow }),
            `${name} ${allow ? "liberado em" : "bloqueado em"} ${AREA_LABELS[area]}.`
          )
        }
        onRemove={(override) =>
          void apply(
            `remove-${override.id}`,
            () => conjoAreasService.removeOverride(workspaceSlug, override.id),
            `A exceção de ${override.member.display_name} em ${AREA_LABELS[override.area]} foi removida.`
          )
        }
      />
    </div>
  );
});

type OverridesProps = {
  workspaceSlug: string;
  overrides: TWorkspaceAreaOverride[];
  saving: string | null;
  onSave: (area: TWorkspaceArea, memberId: string, allow: boolean, name: string) => void;
  onRemove: (override: TWorkspaceAreaOverride) => void;
};

const OverridesSection = observer(function OverridesSection(props: OverridesProps) {
  const { workspaceSlug, overrides, saving, onSave, onRemove } = props;
  const [memberId, setMemberId] = useState<string | null>(null);
  const [area, setArea] = useState<TWorkspaceArea>("clients");
  const {
    workspace: { fetchWorkspaceMembers, workspaceMemberIds, getWorkspaceMemberDetails },
  } = useMember();
  useSWR(`WORKSPACE_MEMBERS_${workspaceSlug}`, () => fetchWorkspaceMembers(workspaceSlug), {
    revalidateOnFocus: false,
  });

  // Exceptions never apply to admins, so they are not offered.
  const candidates = useMemo(
    () =>
      (workspaceMemberIds ?? [])
        .map((id) => getWorkspaceMemberDetails(id))
        .filter(
          (details): details is NonNullable<typeof details> =>
            !!details?.member && details.is_active !== false && details.role !== EUserWorkspaceRoles.ADMIN
        )
        .map((details) => ({
          id: details.member.id,
          name: details.member.display_name || details.member.first_name || details.member.email || "",
          email: details.member.email ?? "",
          role: Number(details.role),
        }))
        .sort((a, b) => a.name.localeCompare(b.name, "pt-BR")),
    [workspaceMemberIds, getWorkspaceMemberDetails]
  );
  const selected = candidates.find((candidate) => candidate.id === memberId) ?? null;

  const memberOptions = candidates.map((candidate) => ({
    value: candidate.id,
    query: `${candidate.name} ${candidate.email}`,
    content: (
      <span className="flex min-w-0 flex-col">
        <span className="truncate">{candidate.name}</span>
        <span className="truncate text-11 text-tertiary">
          {candidate.email} · {ROLE_NAMES[candidate.role] ?? ""}
        </span>
      </span>
    ),
  }));

  const submit = (allow: boolean) => {
    if (!selected) return;
    onSave(area, selected.id, allow, selected.name);
  };

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h3 className="text-14 font-medium text-primary">Exceções por pessoa</h3>
        <p className="text-12 text-tertiary">
          Libere ou bloqueie uma pessoa numa área, acima do papel dela. A exceção nunca bloqueia administradores.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <CustomSearchSelect
          className="w-64"
          customButtonClassName="h-8 rounded-md border border-subtle px-2 text-left"
          customButton={
            <span className={cn("truncate text-13", { "text-placeholder": !selected })}>
              {selected ? selected.name : "Buscar membro"}
            </span>
          }
          value={memberId ?? ""}
          onChange={(value: string) => setMemberId(value)}
          options={memberOptions}
          noChevron
        />
        <CustomSelect
          value={area}
          onChange={(value: TWorkspaceArea) => setArea(value)}
          label={<span className="text-13">{AREA_LABELS[area]}</span>}
          buttonClassName="h-8 rounded-md border border-subtle px-2"
        >
          {(Object.keys(AREA_LABELS) as TWorkspaceArea[]).map((key) => (
            <CustomSelect.Option key={key} value={key}>
              {AREA_LABELS[key]}
            </CustomSelect.Option>
          ))}
        </CustomSelect>
        <Button variant="primary" size="sm" disabled={!selected || saving !== null} onClick={() => submit(true)}>
          Liberar
        </Button>
        <Button variant="secondary" size="sm" disabled={!selected || saving !== null} onClick={() => submit(false)}>
          Bloquear
        </Button>
      </div>

      {overrides.length === 0 ? (
        <p className="text-13 text-placeholder">Nenhuma exceção: todos seguem o papel.</p>
      ) : (
        <div className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
          {overrides.map((override) => (
            <div key={override.id} className="flex items-center gap-3 px-3 py-2">
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-13 text-primary">{override.member.display_name}</span>
                <span className="truncate text-11 text-tertiary">
                  {override.member.email} · {ROLE_NAMES[override.role] ?? ""}
                </span>
              </div>
              <span className="w-36 truncate text-13 text-secondary">{AREA_LABELS[override.area]}</span>
              <span
                className={cn("w-20 rounded-sm px-1.5 py-0.5 text-center text-11 font-medium", {
                  "bg-success-subtle text-success-primary": override.allow,
                  "bg-danger-subtle text-danger-primary": !override.allow,
                })}
              >
                {override.allow ? "Liberado" : "Bloqueado"}
              </span>
              <button
                type="button"
                className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary disabled:opacity-50"
                aria-label={`Remover a exceção de ${override.member.display_name}`}
                disabled={saving !== null}
                onClick={() => onRemove(override)}
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
});
