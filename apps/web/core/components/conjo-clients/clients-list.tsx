/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { AlertTriangle, Building2, Search } from "lucide-react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import type { TClientListItem } from "@plane/types";
import { Input, Loader, ToggleSwitch } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import { ClientFormModal } from "./client-form-modal";
import { EmptyState, PageTitle, useIsClientsAdmin } from "./common";
import { clientsKey, conjoBillingService, formatHours, getErrorMessage, percentOf } from "./helpers";

type Props = { workspaceSlug: string };

export const ClientsList = observer(function ClientsList({ workspaceSlug }: Props) {
  const router = useAppRouter();
  const isAdmin = useIsClientsAdmin(workspaceSlug);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const { data: clients, error } = useSWR(workspaceSlug ? clientsKey(workspaceSlug) : null, () =>
    conjoBillingService.listClients(workspaceSlug)
  );

  const visibleClients = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (clients ?? [])
      .filter((client) => showInactive || client.is_active)
      .filter(
        (client) =>
          !term ||
          client.name.toLowerCase().includes(term) ||
          client.legal_name.toLowerCase().includes(term) ||
          client.document.includes(term)
      );
  }, [clients, query, showInactive]);

  const inactiveCount = (clients ?? []).filter((client) => !client.is_active).length;

  return (
    <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
      <PageTitle
        title="Clientes"
        subtitle="Cadastro dos clientes, contatos, contratos de pacote de horas e saldo de cada um."
        actions={
          isAdmin && (
            <Button variant="primary" size="xl" onClick={() => setIsCreateOpen(true)}>
              Novo cliente
            </Button>
          )
        }
      />

      {error && !clients ? (
        <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
          {getErrorMessage(error, "Não foi possível carregar os clientes. Recarregue a página.")}
        </div>
      ) : !clients ? (
        <Loader className="space-y-2">
          <Loader.Item height="64px" width="100%" />
          <Loader.Item height="64px" width="100%" />
          <Loader.Item height="64px" width="100%" />
        </Loader>
      ) : clients.length === 0 ? (
        <EmptyState
          icon={<Building2 className="size-8" />}
          title="Nenhum cliente cadastrado"
          description="Cadastre os clientes para acompanhar contatos, contratos de pacote de horas e o saldo de cada um."
          action={
            isAdmin && (
              <Button variant="primary" size="lg" onClick={() => setIsCreateOpen(true)}>
                Cadastrar o primeiro cliente
              </Button>
            )
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-[1_1_240px] sm:max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-tertiary" />
              <Input
                aria-label="Buscar cliente"
                placeholder="Buscar por nome ou CNPJ"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full pl-8"
              />
            </div>
            {inactiveCount > 0 && (
              <div className="flex items-center gap-2 text-13 text-secondary">
                <ToggleSwitch
                  value={showInactive}
                  onChange={() => setShowInactive(!showInactive)}
                  label="Mostrar inativos"
                  size="sm"
                />
                <span>Mostrar inativos ({inactiveCount})</span>
              </div>
            )}
          </div>

          {visibleClients.length === 0 ? (
            <EmptyState title="Nenhum cliente encontrado" description="Ajuste a busca ou mostre os inativos." />
          ) : (
            <ul className="flex flex-col overflow-hidden rounded-lg border border-subtle bg-layer-1">
              {visibleClients.map((client) => (
                <ClientRow key={client.id} client={client} href={`/${workspaceSlug}/clients/${client.id}`} />
              ))}
            </ul>
          )}
        </>
      )}

      <ClientFormModal
        isOpen={isCreateOpen}
        workspaceSlug={workspaceSlug}
        onClose={() => setIsCreateOpen(false)}
        onSaved={(client) => router.push(`/${workspaceSlug}/clients/${client.id}`)}
      />
    </div>
  );
});

function ClientRow({ client, href }: { client: TClientListItem; href: string }) {
  const pkg = client.package;
  const projectsCount = client.project_ids.length;
  return (
    <li className="border-b border-subtle last:border-b-0">
      <Link
        href={href}
        className={cn(
          "grid grid-cols-1 items-center gap-x-6 gap-y-2 px-4 py-3 hover:bg-layer-1-hover sm:grid-cols-[minmax(0,1fr)_220px_110px]",
          { "opacity-60": !client.is_active }
        )}
      >
        <div className="flex min-w-0 flex-col">
          <span className="flex items-center gap-2">
            <span className="truncate text-14 font-medium text-primary">{client.name}</span>
            {!client.is_active && (
              <span className="rounded-full bg-layer-3 px-2 py-0.5 text-11 font-semibold text-secondary">Inativo</span>
            )}
          </span>
          <span className="truncate text-12 text-tertiary">
            {[client.legal_name, client.document].filter(Boolean).join(" · ") || "Sem razão social cadastrada"}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          {pkg ? (
            <>
              <span className="flex items-center gap-1.5 text-13">
                <span className="font-semibold text-primary">{formatHours(pkg.available)}</span>
                <span className="text-tertiary">de {formatHours(pkg.max_balance)}</span>
                {pkg.low_balance && (
                  <span className="flex items-center gap-1 text-12 font-medium text-warning-primary">
                    <AlertTriangle className="size-3.5" aria-hidden />
                    Saldo baixo
                  </span>
                )}
              </span>
              <span className="h-1.5 w-full overflow-hidden rounded-full bg-layer-3" aria-hidden>
                <span
                  className={cn("block h-full rounded-full", pkg.low_balance ? "bg-warning-primary" : "bg-inverse")}
                  style={{ width: `${percentOf(pkg.available, pkg.max_balance)}%` }}
                />
              </span>
            </>
          ) : (
            <span className="text-12 text-tertiary">Sem contrato ativo</span>
          )}
        </div>

        <span className="text-12 text-secondary sm:text-right">
          {projectsCount === 0 ? "Nenhum projeto" : projectsCount === 1 ? "1 projeto" : `${projectsCount} projetos`}
        </span>
      </Link>
    </li>
  );
}
