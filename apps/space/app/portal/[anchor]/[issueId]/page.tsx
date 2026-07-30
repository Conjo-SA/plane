/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ArrowLeft } from "lucide-react";
import { useParams } from "next/navigation";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import { IntakePortalService } from "@plane/services";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PoweredBy } from "@/components/common/powered-by";
import { PageNotFound } from "@/components/ui/not-found";
// helpers
import { getPortalSession } from "@/helpers/portal-session";

const intakePortalService = new IntakePortalService();

const formatDateTime = (value: string) => new Date(value).toLocaleString("pt-BR");

export default function PortalTicketDetailPage() {
    // params
    const { anchor, issueId } = useParams<{ anchor: string; issueId: string }>();
    const session = anchor ? getPortalSession(anchor) : null;
    // ticket
    const {
        data: ticket,
        error,
        isLoading,
    } = useSWR(
        anchor && issueId && session ? `PORTAL_TICKET_${anchor}_${issueId}` : null,
        anchor && issueId && session ? () => intakePortalService.retrieveTicket(anchor, issueId, session.token) : null
    );

    if (!session)
        return (
            <div className="flex h-screen w-full flex-col items-center justify-center gap-4 bg-surface-2">
                <p className="text-14 text-secondary">Sua sessão expirou.</p>
                <Link to={`/portal/${anchor}`} className="text-13 text-accent-primary hover:underline">
                    Entrar novamente
                </Link>
            </div>
        );

    if (isLoading)
        return (
            <div className="flex h-screen w-full items-center justify-center bg-surface-2">
                <LogoSpinner />
            </div>
        );

    if (error || !ticket) return <PageNotFound />;

    return (
        <>
            <div className="min-h-screen w-full overflow-y-auto bg-gradient-to-b from-surface-2 via-surface-2 to-surface-1">
                <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:py-14">
                    <Link
                        to={`/portal/${anchor}`}
                        className="mb-4 inline-flex items-center gap-1.5 text-13 text-tertiary transition-colors hover:text-primary"
                    >
                        <ArrowLeft className="size-3.5" />
                        Voltar para meus chamados
                    </Link>

                    <div className="overflow-hidden rounded-2xl border border-subtle bg-surface-1 shadow-raised-200">
                        <div className="border-b border-subtle-1 bg-gradient-to-r from-accent-subtle to-surface-1 px-6 py-6 sm:px-9">
                            <p className="text-11 font-medium tracking-wide text-tertiary uppercase">
                                #{ticket.sequence_id} · {ticket.project_name}
                            </p>
                            <h1 className="mt-1 text-20 leading-tight font-semibold text-primary">{ticket.name}</h1>
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-12 text-tertiary">
                                {ticket.state && (
                                    <span className="rounded-full border border-subtle bg-surface-1 px-2.5 py-1 font-medium text-secondary">
                                        {ticket.state}
                                    </span>
                                )}
                                <span>Aberto em {formatDateTime(ticket.created_at)}</span>
                            </div>
                        </div>

                        <div className="space-y-6 px-6 py-7 sm:px-9">
                            <div>
                                <h2 className="text-13 font-medium text-secondary">Descrição</h2>
                                <div
                                    className="prose prose-sm mt-2 max-w-none text-14 text-secondary"
                                    // The API sanitizes this HTML before storing it
                                    dangerouslySetInnerHTML={{ __html: ticket.description_html || "<p>Sem descrição.</p>" }}
                                />
                            </div>

                            <div>
                                <h2 className="text-13 font-medium text-secondary">Atualizações</h2>
                                {ticket.comments.length === 0 ? (
                                    <p className="mt-2 text-13 text-tertiary">Ainda não há atualizações públicas neste chamado.</p>
                                ) : (
                                    <ul className="mt-3 space-y-3">
                                        {ticket.comments.map((comment) => (
                                            <li key={comment.id} className="rounded-md border border-subtle bg-surface-2 px-4 py-3">
                                                <p className="text-11 text-tertiary">{formatDateTime(comment.created_at)}</p>
                                                <div
                                                    className="prose prose-sm mt-1 max-w-none text-14 text-secondary"
                                                    dangerouslySetInnerHTML={{ __html: comment.comment_html }}
                                                />
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <PoweredBy />
        </>
    );
}
