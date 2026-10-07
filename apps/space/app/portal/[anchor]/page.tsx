/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ArrowLeft, ChevronRight, LogOut, Ticket } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { IntakePortalService } from "@plane/services";
import type { TIntakePortalTicket } from "@plane/types";
import { Input } from "@plane/ui";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PoweredBy } from "@/components/common/powered-by";
import { PortalChip } from "@/components/portal/chip";
import { PortalPackageBalanceCard } from "@/components/portal/package-balance";
import { PageNotFound } from "@/components/ui/not-found";
// helpers
import { clearPortalSession, getPortalSession, setPortalSession } from "@/helpers/portal-session";
import { getPortalTicketStatus } from "@/helpers/portal-ticket-status";
import type { TPortalTicketBucket } from "@/helpers/portal-ticket-status";

const intakePortalService = new IntakePortalService();

const SECTIONS: { bucket: TPortalTicketBucket; title: string; empty: string | null }[] = [
  { bucket: "action", title: "Precisa da sua ação", empty: null },
  { bucket: "open", title: "Em aberto", empty: "Nenhum chamado em aberto no momento." },
  { bucket: "closed", title: "Concluídos", empty: null },
];

const formatDate = (value: string) => new Date(value).toLocaleDateString("pt-BR");

const readError = (err: unknown) => (err as { data?: { error?: string } })?.data?.error;

export default function PortalTicketsPage() {
  // params
  const { anchor } = useParams<{ anchor: string }>();
  // states
  const [session, setSession] = useState(() => (anchor ? getPortalSession(anchor) : null));
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // portal meta
  const { data: portal, error: portalError } = useSWR(
    anchor ? `INTAKE_PORTAL_${anchor}` : null,
    anchor ? () => intakePortalService.retrieveMeta(anchor) : null
  );
  // tickets
  const {
    data: ticketList,
    error: ticketsError,
    isLoading: areTicketsLoading,
  } = useSWR(
    anchor && session ? `PORTAL_TICKETS_${anchor}_${session.email}` : null,
    anchor && session ? () => intakePortalService.listTickets(anchor, session.token) : null
  );

  const handleRequestCode = async () => {
    if (!anchor) return;
    setFormError(null);
    setIsSubmitting(true);
    try {
      await intakePortalService.requestVerificationCode(anchor, email);
      setStep("code");
    } catch (err) {
      setFormError(readError(err) || "Não foi possível enviar o código. Tente novamente.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmCode = async () => {
    if (!anchor) return;
    setFormError(null);
    setIsSubmitting(true);
    try {
      const response = await intakePortalService.confirmVerificationCode(anchor, email, code);
      setPortalSession(anchor, response);
      setSession(response);
      setCode("");
    } catch (err) {
      setFormError(readError(err) || "Código inválido. Tente novamente.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleLogout = () => {
    if (!anchor) return;
    clearPortalSession(anchor);
    setSession(null);
    setStep("email");
    setEmail("");
  };

  if (portalError || !portal) return portalError ? <PageNotFound /> : null;

  // Session expired on the server side
  if (session && (ticketsError as { status?: number })?.status === 401) {
    clearPortalSession(anchor);
  }

  return (
    <>
      <div className="min-h-screen w-full overflow-y-auto bg-gradient-to-b from-surface-2 via-surface-2 to-surface-1">
        <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:py-14">
          <div className="overflow-hidden rounded-2xl border border-subtle bg-surface-1 shadow-raised-200">
            <div className="flex items-center justify-between gap-4 border-b border-subtle-1 bg-gradient-to-r from-accent-subtle to-surface-1 px-6 py-6 sm:px-9">
              <div className="min-w-0">
                <p className="text-11 font-medium tracking-wide text-tertiary uppercase">
                  {portal.workspace_name} · {portal.project_name}
                </p>
                <h1 className="mt-1 text-20 font-semibold text-primary">Meus chamados</h1>
              </div>
              {session && (
                <Button variant="secondary" size="sm" onClick={handleLogout} prependIcon={<LogOut />}>
                  Sair
                </Button>
              )}
            </div>

            <div className="px-6 py-7 sm:px-9">
              {!session ? (
                <div className="mx-auto max-w-sm space-y-4">
                  <div className="text-center">
                    <h2 className="text-16 font-semibold text-primary">
                      {step === "email" ? "Acesse seus chamados" : "Confirme o código"}
                    </h2>
                    <p className="mt-1 text-13 text-secondary">
                      {step === "email"
                        ? "Informe o e-mail usado para abrir os chamados. Enviaremos um código de acesso."
                        : `Enviamos um código de 6 dígitos para ${email}.`}
                    </p>
                  </div>

                  {step === "email" ? (
                    <div className="space-y-3">
                      <Input
                        type="email"
                        className="w-full"
                        placeholder="voce@empresa.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                      />
                      <Button
                        variant="primary"
                        className="w-full"
                        loading={isSubmitting}
                        disabled={!email}
                        onClick={() => void handleRequestCode()}
                      >
                        Enviar código
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <Input
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        className="w-full text-center tracking-[0.4em]"
                        placeholder="000000"
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                      />
                      <Button
                        variant="primary"
                        className="w-full"
                        loading={isSubmitting}
                        disabled={code.length < 6}
                        onClick={() => void handleConfirmCode()}
                      >
                        Entrar
                      </Button>
                      <button
                        type="button"
                        className="flex w-full items-center justify-center gap-1 text-12 text-tertiary hover:text-primary"
                        onClick={() => {
                          setStep("email");
                          setCode("");
                          setFormError(null);
                        }}
                      >
                        <ArrowLeft className="size-3.5" />
                        Usar outro e-mail
                      </button>
                    </div>
                  )}

                  {formError && (
                    <p className="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-13 text-danger-primary">
                      {formError}
                    </p>
                  )}
                </div>
              ) : areTicketsLoading ? (
                <div className="flex justify-center py-12">
                  <LogoSpinner />
                </div>
              ) : (
                <div className="space-y-5">
                  {ticketList?.package && <PortalPackageBalanceCard pkg={ticketList.package} />}
                  {!ticketList?.tickets?.length ? (
                    <div className="flex flex-col items-center gap-3 py-12 text-center">
                      <Ticket className="size-8 text-tertiary" />
                      <p className="text-14 text-secondary">Nenhum chamado encontrado para {session.email}.</p>
                    </div>
                  ) : (
                    <PortalTicketSections anchor={anchor} tickets={ticketList.tickets} />
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      <PoweredBy />
    </>
  );
}

/** Tickets grouped by what they need: the requester's action first, then what is still open, then history. */
function PortalTicketSections(props: { anchor: string; tickets: TIntakePortalTicket[] }) {
  const { anchor, tickets } = props;
  const rows = tickets.map((ticket) => ({ ticket, status: getPortalTicketStatus(ticket) }));
  const count = (bucket: TPortalTicketBucket) => rows.filter((row) => row.status.bucket === bucket).length;
  const openCount = count("open");
  const actionCount = count("action");

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-2">
        <SummaryTile label="Precisam de você" value={actionCount} highlight={actionCount > 0} />
        <SummaryTile label="Em aberto" value={openCount} />
        <SummaryTile label="Concluídos" value={count("closed")} />
      </div>

      {SECTIONS.map(({ bucket, title, empty }) => {
        const items = rows.filter((row) => row.status.bucket === bucket);
        if (!items.length && !empty) return null;
        const list = items.length ? (
          <ul className="divide-y divide-subtle-1 overflow-hidden rounded-lg border border-subtle">
            {items.map(({ ticket, status }) => (
              <li key={ticket.id}>
                <Link
                  to={`/portal/${anchor}/${ticket.id}`}
                  className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-layer-1 sm:gap-4"
                >
                  <span className="w-1 shrink-0 self-stretch rounded-full" style={{ backgroundColor: status.color }} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                      <p className="line-clamp-2 text-14 font-medium text-primary sm:truncate">{ticket.name}</p>
                      <PortalChip label={status.label} color={status.color} />
                    </div>
                    {(status.hint || ticket.work_kind === "maintenance") && (
                      <p className="mt-1 text-12 text-secondary">
                        {[
                          status.hint,
                          ticket.work_kind === "maintenance" ? "Correção de bug, não desconta do pacote" : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                    <p className="mt-0.5 text-11 text-tertiary">
                      #{ticket.sequence_id} · aberto em {formatDate(ticket.created_at)}
                      {ticket.updated_at ? ` · atualizado em ${formatDate(ticket.updated_at)}` : ""}
                    </p>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-tertiary" />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-lg border border-dashed border-subtle px-4 py-5 text-center text-13 text-tertiary">
            {empty}
          </p>
        );

        if (bucket === "closed")
          return (
            <details key={bucket} className="group" open={!openCount && !actionCount}>
              <summary className="mb-2 flex cursor-pointer list-none items-center gap-1.5 text-13 font-semibold text-primary">
                <ChevronRight className="size-4 text-tertiary transition-transform group-open:rotate-90" />
                {title} ({items.length})
              </summary>
              {list}
            </details>
          );
        return (
          <section key={bucket}>
            <h2 className="mb-2 text-13 font-semibold text-primary">
              {title} ({items.length})
            </h2>
            {list}
          </section>
        );
      })}
    </div>
  );
}

function SummaryTile(props: { label: string; value: number; highlight?: boolean }) {
  const { label, value, highlight = false } = props;
  return (
    <div
      className="rounded-lg border border-subtle px-3 py-2.5"
      style={highlight ? { borderColor: "#C2410C66", backgroundColor: "#C2410C0D" } : undefined}
    >
      <p className="text-20 font-semibold text-primary" style={highlight ? { color: "#C2410C" } : undefined}>
        {value}
      </p>
      <p className="text-12 text-secondary">{label}</p>
    </div>
  );
}
