/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ArrowLeft, LogOut, Ticket } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { IntakePortalService } from "@plane/services";
import { Input } from "@plane/ui";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PoweredBy } from "@/components/common/powered-by";
import { PageNotFound } from "@/components/ui/not-found";
// helpers
import { clearPortalSession, getPortalSession, setPortalSession } from "@/helpers/portal-session";

const intakePortalService = new IntakePortalService();

const STATE_STYLES: Record<string, string> = {
    backlog: "bg-neutral-100 text-neutral-700",
    unstarted: "bg-sky-100 text-sky-700",
    started: "bg-amber-100 text-amber-700",
    completed: "bg-emerald-100 text-emerald-700",
    cancelled: "bg-red-100 text-red-700",
    triage: "bg-violet-100 text-violet-700",
};

const formatDate = (value: string) => new Date(value).toLocaleDateString("pt-BR");

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

    const readError = (err: unknown) => (err as { data?: { error?: string } })?.data?.error;

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
                            ) : !ticketList?.tickets?.length ? (
                                <div className="flex flex-col items-center gap-3 py-12 text-center">
                                    <Ticket className="size-8 text-tertiary" />
                                    <p className="text-14 text-secondary">Nenhum chamado encontrado para {session.email}.</p>
                                </div>
                            ) : (
                                <ul className="divide-y divide-subtle-1 overflow-hidden rounded-lg border border-subtle">
                                    {ticketList.tickets.map((ticket) => (
                                        <li key={ticket.id}>
                                            <Link
                                                to={`/portal/${anchor}/${ticket.id}`}
                                                className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-layer-1"
                                            >
                                                <div className="min-w-0 flex-1">
                                                    <p className="truncate text-14 font-medium text-primary">{ticket.name}</p>
                                                    <p className="mt-0.5 text-11 text-tertiary">
                                                        #{ticket.sequence_id} · {ticket.project_name} · {formatDate(ticket.created_at)}
                                                    </p>
                                                </div>
                                                {ticket.state && (
                                                    <span
                                                        className={`shrink-0 rounded-full px-2.5 py-1 text-11 font-medium ${STATE_STYLES[ticket.state_group ?? ""] ?? "bg-neutral-100 text-neutral-700"
                                                            }`}
                                                    >
                                                        {ticket.state}
                                                    </span>
                                                )}
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </div>
            <PoweredBy />
        </>
    );
}
