/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { mutate as globalMutate } from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { Loader } from "@plane/ui";
// hooks
import { useUser } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import { ClientFormModal } from "./client-form-modal";
import { ReportPeriodModal, reportHref } from "./client-report";
import { PageTitle, useIsClientsAdmin } from "./common";
import { ContactsCard } from "./contacts-card";
import { ContractProjectsCard } from "./contract-projects-card";
import { clientKey, clientsKey, conjoBillingService, formatMonthYear, getErrorMessage } from "./helpers";
import { NoteModal } from "./note-modal";
import { PackageBalanceCard } from "./package-balance-card";
import { ClientTimeline } from "./timeline";

type Props = { workspaceSlug: string; clientId: string };

export const ClientDetail = observer(function ClientDetail({ workspaceSlug, clientId }: Props) {
  const isAdmin = useIsClientsAdmin(workspaceSlug);
  const { data: currentUser } = useUser();
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isNoteOpen, setIsNoteOpen] = useState(false);
  const [isReportOpen, setIsReportOpen] = useState(false);
  const router = useAppRouter();
  const [timelineToken, setTimelineToken] = useState(0);

  const {
    data: client,
    error,
    mutate,
  } = useSWR(workspaceSlug && clientId ? clientKey(workspaceSlug, clientId) : null, () =>
    conjoBillingService.getClient(workspaceSlug, clientId)
  );

  /** Reloads the client and the list (balance, projects count) after a write. */
  const refresh = async () => {
    await mutate();
    void globalMutate(clientsKey(workspaceSlug));
  };

  if (error && !client)
    return (
      <div className="mx-auto w-full max-w-[1232px] px-4 py-6 md:px-6">
        <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
          {getErrorMessage(error, "Não foi possível carregar o cliente. Recarregue a página.")}
        </div>
      </div>
    );

  if (!client)
    return (
      <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
        <Loader className="space-y-2">
          <Loader.Item height="20px" width="160px" />
          <Loader.Item height="32px" width="320px" />
        </Loader>
        <div className="flex flex-wrap items-start gap-5">
          <Loader className="flex flex-[1_1_320px] flex-col gap-4 lg:max-w-[380px]">
            <Loader.Item height="200px" width="100%" />
            <Loader.Item height="140px" width="100%" />
            <Loader.Item height="120px" width="100%" />
          </Loader>
          <Loader className="flex min-w-0 flex-[999_1_560px] flex-col gap-3">
            <Loader.Item height="40px" width="100%" />
            <Loader.Item height="56px" width="100%" />
            <Loader.Item height="56px" width="100%" />
            <Loader.Item height="56px" width="100%" />
          </Loader>
        </div>
      </div>
    );

  const base = `/${workspaceSlug}/clients/${client.id}`;
  const projectsCount = client.projects.length;
  const labelsCount = client.labels.length;
  const subtitle = [
    client.document ? `CNPJ ${client.document}` : null,
    client.created_at ? `cliente desde ${formatMonthYear(client.created_at)}` : null,
    projectsCount === 1 ? "1 projeto" : `${projectsCount} projetos`,
    labelsCount === 0 ? null : labelsCount === 1 ? "1 etiqueta" : `${labelsCount} etiquetas`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
      <PageTitle
        trail={[{ label: "Clientes", href: `/${workspaceSlug}/clients` }, { label: client.name }]}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {client.legal_name || client.name}
            {!client.is_active && (
              <span className="rounded-full bg-layer-3 px-2 py-0.5 text-11 font-semibold text-secondary">Inativo</span>
            )}
          </span>
        }
        subtitle={
          <>
            {subtitle}
            {client.notes && <p className="mt-1 text-12 whitespace-pre-wrap text-tertiary">{client.notes}</p>}
          </>
        }
        actions={
          <>
            {isAdmin && (
              <Button variant="secondary" size="xl" onClick={() => setIsEditOpen(true)}>
                Editar
              </Button>
            )}
            <Link
              href={`${base}/ledger`}
              className="inline-flex h-8 items-center rounded-md border border-strong bg-layer-2 px-3 text-body-sm-medium text-secondary hover:bg-layer-2-hover"
            >
              Ver extrato
            </Link>
            <Button variant="secondary" size="xl" onClick={() => setIsReportOpen(true)}>
              Emitir relatório
            </Button>
            <Button variant="primary" size="xl" onClick={() => setIsNoteOpen(true)}>
              Registrar contato
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-start gap-5">
        <aside className="flex w-full min-w-0 flex-[1_1_320px] flex-col gap-4 lg:max-w-[380px]">
          <PackageBalanceCard
            pkg={client.package}
            maintenanceMinutes={client.maintenance_minutes_this_month}
            newContractHref={isAdmin ? `${base}/contract` : undefined}
          />
          <ContactsCard workspaceSlug={workspaceSlug} client={client} isAdmin={isAdmin} onChanged={refresh} />
          <ContractProjectsCard workspaceSlug={workspaceSlug} client={client} isAdmin={isAdmin} onChanged={refresh} />
        </aside>

        <div className="w-full min-w-0 flex-[999_1_560px]">
          <ClientTimeline
            workspaceSlug={workspaceSlug}
            clientId={client.id}
            isAdmin={isAdmin}
            currentUserName={currentUser?.display_name}
            refreshToken={timelineToken}
          />
        </div>
      </div>

      <ClientFormModal
        isOpen={isEditOpen}
        workspaceSlug={workspaceSlug}
        client={client}
        onClose={() => setIsEditOpen(false)}
        onSaved={refresh}
      />
      <ReportPeriodModal
        isOpen={isReportOpen}
        title="Emitir relatório"
        submitLabel="Gerar relatório"
        onClose={() => setIsReportOpen(false)}
        onSubmit={(period) => router.push(reportHref(workspaceSlug, client.id, period))}
      />
      <NoteModal
        isOpen={isNoteOpen}
        workspaceSlug={workspaceSlug}
        clientId={client.id}
        contacts={client.contacts}
        onClose={() => setIsNoteOpen(false)}
        onSaved={async () => setTimelineToken((token) => token + 1)}
      />
    </div>
  );
});
