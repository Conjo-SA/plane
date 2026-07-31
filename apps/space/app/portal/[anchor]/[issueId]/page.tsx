/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ArrowLeft, Download, FileText, Loader2, Paperclip, Send, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { IntakePortalService } from "@plane/services";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PoweredBy } from "@/components/common/powered-by";
import { PageNotFound } from "@/components/ui/not-found";
// helpers
import { getPortalSession } from "@/helpers/portal-session";

const intakePortalService = new IntakePortalService();

const MAX_ATTACHMENTS = 10;

const STATE_STYLES: Record<string, string> = {
    backlog: "bg-neutral-100 text-neutral-700",
    unstarted: "bg-sky-100 text-sky-700",
    started: "bg-amber-100 text-amber-700",
    completed: "bg-emerald-100 text-emerald-700",
    cancelled: "bg-red-100 text-red-700",
    triage: "bg-violet-100 text-violet-700",
};

const PRIORITY_LABELS: Record<string, string> = {
    urgent: "Urgente",
    high: "Alta",
    medium: "Média",
    low: "Baixa",
    none: "Sem prioridade",
};

const PRIORITY_STYLES: Record<string, string> = {
    urgent: "bg-red-100 text-red-700",
    high: "bg-orange-100 text-orange-700",
    medium: "bg-amber-100 text-amber-700",
    low: "bg-sky-100 text-sky-700",
    none: "bg-neutral-100 text-neutral-700",
};

// Mirrors IntakeIssueStatus on the API side.
const INTAKE_STATUS_LABELS: Record<number, string> = {
    [-2]: "Em triagem",
    [-1]: "Recusado",
    0: "Adiado",
    1: "Aceito",
    2: "Duplicado",
};

type TPendingAttachment = {
    key: string;
    name: string;
    size: number;
    assetId?: string;
    status: "uploading" | "done" | "error";
};

const formatDateTime = (value: string) => new Date(value).toLocaleString("pt-BR");

const formatDate = (value: string) => new Date(value).toLocaleDateString("pt-BR");

const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/** Turn the plain text reply into safe HTML. The API sanitizes it again on save. */
const textToHtml = (value: string): string =>
    value
        .trim()
        .split(/\n{2,}/)
        .map(
            (paragraph) =>
                `<p>${paragraph
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/\n/g, "<br/>")}</p>`
        )
        .join("");

export default function PortalTicketDetailPage() {
    // params
    const { anchor, issueId } = useParams<{ anchor: string; issueId: string }>();
    const session = anchor ? getPortalSession(anchor) : null;
    // states
    const [reply, setReply] = useState("");
    const [pendingAttachments, setPendingAttachments] = useState<TPendingAttachment[]>([]);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    // refs
    const fileInputRef = useRef<HTMLInputElement>(null);
    // ticket
    const {
        data: ticket,
        error,
        isLoading,
        mutate,
    } = useSWR(
        anchor && issueId && session ? `PORTAL_TICKET_${anchor}_${issueId}` : null,
        anchor && issueId && session ? () => intakePortalService.retrieveTicket(anchor, issueId, session.token) : null
    );

    const readError = (err: unknown) => (err as { data?: { error?: string } })?.data?.error;

    const isUploading = pendingAttachments.some((attachment) => attachment.status === "uploading");

    const handleFiles = async (files: FileList | null) => {
        if (!files || !anchor) return;
        setFormError(null);

        const incoming = Array.from(files).slice(0, MAX_ATTACHMENTS - pendingAttachments.length);
        if (incoming.length === 0) {
            setFormError(`Você pode anexar no máximo ${MAX_ATTACHMENTS} arquivos.`);
            return;
        }

        for (const file of incoming) {
            const key = `${file.name}-${file.size}-${Date.now()}-${Math.random()}`;
            setPendingAttachments((prev) => [...prev, { key, name: file.name, size: file.size, status: "uploading" }]);

            try {
                const assetId = await intakePortalService.uploadAsset(anchor, file);
                setPendingAttachments((prev) =>
                    prev.map((item) => (item.key === key ? { ...item, assetId, status: "done" } : item))
                );
            } catch (err) {
                setFormError(readError(err) || `Não foi possível enviar o arquivo "${file.name}".`);
                setPendingAttachments((prev) =>
                    prev.map((item) => (item.key === key ? { ...item, status: "error" } : item))
                );
            }
        }
    };

    const handleRemovePending = (key: string) =>
        setPendingAttachments((prev) => prev.filter((attachment) => attachment.key !== key));

    const handleDownload = async (assetId: string) => {
        if (!anchor || !issueId || !session) return;
        try {
            const url = await intakePortalService.retrieveAttachmentUrl(anchor, issueId, assetId, session.token);
            if (url) window.open(url, "_blank", "noopener,noreferrer");
        } catch (err) {
            setFormError(readError(err) || "Não foi possível abrir o anexo.");
        }
    };

    const handleSubmit = async () => {
        if (!anchor || !issueId || !session) return;
        setFormError(null);

        if (isUploading) {
            setFormError("Aguarde o envio dos anexos terminar.");
            return;
        }

        const uploadedIds = pendingAttachments
            .filter((attachment) => attachment.status === "done" && attachment.assetId)
            .map((attachment) => attachment.assetId as string);
        const message = reply.trim();

        if (!message && uploadedIds.length === 0) {
            setFormError("Escreva uma mensagem ou anexe um arquivo.");
            return;
        }

        setIsSubmitting(true);
        try {
            if (message) {
                await intakePortalService.createTicketComment(
                    anchor,
                    issueId,
                    { comment_html: textToHtml(message), attachment_ids: uploadedIds },
                    session.token
                );
            } else {
                await intakePortalService.attachTicketFiles(anchor, issueId, uploadedIds, session.token);
            }
            setReply("");
            setPendingAttachments([]);
            await mutate();
        } catch (err) {
            setFormError(readError(err) || "Não foi possível enviar sua mensagem. Tente novamente.");
        } finally {
            setIsSubmitting(false);
        }
    };

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

    // The API may omit these collections (or return a non-array) on older
    // deployments, so normalize before rendering to keep the page from crashing.
    const comments = Array.isArray(ticket.comments) ? ticket.comments : [];
    const attachments = Array.isArray(ticket.attachments) ? ticket.attachments : [];
    const labels = Array.isArray(ticket.labels) ? ticket.labels : [];
    const assignees = Array.isArray(ticket.assignees) ? ticket.assignees : [];
    const canAttach = ticket.is_attachment_enabled !== false;
    const ticketCode = ticket.project_identifier
        ? `${ticket.project_identifier}-${ticket.sequence_id}`
        : `#${ticket.sequence_id}`;
    const priority = ticket.priority ?? "none";
    const intakeStatusLabel = INTAKE_STATUS_LABELS[ticket.intake_status];

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
                                {ticketCode} · {ticket.project_name}
                            </p>
                            <h1 className="mt-1 text-20 leading-tight font-semibold text-primary">{ticket.name}</h1>
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-12 text-tertiary">
                                {ticket.state && (
                                    <span
                                        className={`rounded-full px-2.5 py-1 text-11 font-medium ${STATE_STYLES[ticket.state_group ?? ""] ?? "bg-neutral-100 text-neutral-700"
                                            }`}
                                    >
                                        {ticket.state}
                                    </span>
                                )}
                                <span
                                    className={`rounded-full px-2.5 py-1 text-11 font-medium ${PRIORITY_STYLES[priority] ?? PRIORITY_STYLES.none
                                        }`}
                                >
                                    {PRIORITY_LABELS[priority] ?? PRIORITY_LABELS.none}
                                </span>
                                {intakeStatusLabel && (
                                    <span className="rounded-full border border-subtle bg-surface-1 px-2.5 py-1 text-11 font-medium text-secondary">
                                        {intakeStatusLabel}
                                    </span>
                                )}
                            </div>
                        </div>

                        <div className="space-y-6 px-6 py-7 sm:px-9">
                            <div>
                                <h2 className="text-13 font-medium text-secondary">Detalhes</h2>
                                <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
                                    <div className="flex items-start gap-2">
                                        <dt className="w-32 shrink-0 text-12 text-tertiary">Aberto em</dt>
                                        <dd className="text-13 text-primary">{formatDateTime(ticket.created_at)}</dd>
                                    </div>
                                    {ticket.updated_at && (
                                        <div className="flex items-start gap-2">
                                            <dt className="w-32 shrink-0 text-12 text-tertiary">Última atualização</dt>
                                            <dd className="text-13 text-primary">{formatDateTime(ticket.updated_at)}</dd>
                                        </div>
                                    )}
                                    {ticket.target_date && (
                                        <div className="flex items-start gap-2">
                                            <dt className="w-32 shrink-0 text-12 text-tertiary">Previsão</dt>
                                            <dd className="text-13 text-primary">{formatDate(ticket.target_date)}</dd>
                                        </div>
                                    )}
                                    {ticket.completed_at && (
                                        <div className="flex items-start gap-2">
                                            <dt className="w-32 shrink-0 text-12 text-tertiary">Concluído em</dt>
                                            <dd className="text-13 text-primary">{formatDateTime(ticket.completed_at)}</dd>
                                        </div>
                                    )}
                                    <div className="flex items-start gap-2">
                                        <dt className="w-32 shrink-0 text-12 text-tertiary">Responsável</dt>
                                        <dd className="text-13 text-primary">
                                            {assignees.length > 0 ? assignees.join(", ") : "Ainda não atribuído"}
                                        </dd>
                                    </div>
                                    <div className="flex items-start gap-2">
                                        <dt className="w-32 shrink-0 text-12 text-tertiary">Etiquetas</dt>
                                        <dd className="flex flex-wrap gap-1.5">
                                            {labels.length === 0 ? (
                                                <span className="text-13 text-tertiary">Nenhuma</span>
                                            ) : (
                                                labels.map((label) => (
                                                    <span
                                                        key={label.name}
                                                        className="inline-flex items-center gap-1.5 rounded-full border border-subtle bg-surface-1 px-2 py-0.5 text-11 text-secondary"
                                                    >
                                                        <span
                                                            aria-hidden
                                                            className="size-2 shrink-0 rounded-full"
                                                            style={{ backgroundColor: label.color || "#6b7280" }}
                                                        />
                                                        {label.name}
                                                    </span>
                                                ))
                                            )}
                                        </dd>
                                    </div>
                                </dl>
                            </div>

                            <div>
                                <h2 className="text-13 font-medium text-secondary">Descrição</h2>
                                <div
                                    className="prose prose-sm mt-2 max-w-none text-14 text-secondary"
                                    // The API sanitizes this HTML before storing it
                                    dangerouslySetInnerHTML={{ __html: ticket.description_html || "<p>Sem descrição.</p>" }}
                                />
                            </div>

                            <div>
                                <h2 className="text-13 font-medium text-secondary">Anexos</h2>
                                {attachments.length === 0 ? (
                                    <p className="mt-2 text-13 text-tertiary">Nenhum arquivo anexado a este chamado.</p>
                                ) : (
                                    <ul className="mt-3 space-y-2">
                                        {attachments.map((attachment) => (
                                            <li
                                                key={attachment.id}
                                                className="flex items-center gap-3 rounded-md border border-subtle bg-surface-2 px-3 py-2"
                                            >
                                                <FileText className="size-4 shrink-0 text-tertiary" />
                                                <div className="min-w-0 flex-1">
                                                    <p className="truncate text-13 text-primary">{attachment.name}</p>
                                                    <p className="text-11 text-tertiary">
                                                        {formatFileSize(attachment.size)} · {formatDateTime(attachment.created_at)}
                                                    </p>
                                                </div>
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    prependIcon={<Download />}
                                                    onClick={() => void handleDownload(attachment.id)}
                                                >
                                                    Baixar
                                                </Button>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>

                            <div>
                                <h2 className="text-13 font-medium text-secondary">Atualizações</h2>
                                {comments.length === 0 ? (
                                    <p className="mt-2 text-13 text-tertiary">Ainda não há atualizações públicas neste chamado.</p>
                                ) : (
                                    <ul className="mt-3 space-y-3">
                                        {comments.map((comment) => (
                                            <li
                                                key={comment.id}
                                                className={`rounded-md border px-4 py-3 ${comment.is_requester
                                                        ? "border-accent-subtle bg-accent-subtle"
                                                        : "border-subtle bg-surface-2"
                                                    }`}
                                            >
                                                <p className="text-11 text-tertiary">
                                                    {comment.author} · {formatDateTime(comment.created_at)}
                                                </p>
                                                <div
                                                    className="prose prose-sm mt-1 max-w-none text-14 text-secondary"
                                                    // The API sanitizes this HTML before storing it
                                                    dangerouslySetInnerHTML={{ __html: comment.comment_html }}
                                                />
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>

                            <div className="space-y-3 border-t border-subtle-1 pt-5">
                                <h2 className="text-13 font-medium text-secondary">Responder</h2>
                                <textarea
                                    className="min-h-[120px] w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-14 text-primary outline-none transition-colors placeholder:text-placeholder focus:border-strong"
                                    placeholder="Escreva uma atualização, responda a equipe ou envie mais detalhes."
                                    value={reply}
                                    onChange={(e) => setReply(e.target.value)}
                                />

                                {canAttach && (
                                    <div className="space-y-2">
                                        <Button
                                            variant="secondary"
                                            size="sm"
                                            prependIcon={<Paperclip />}
                                            disabled={pendingAttachments.length >= MAX_ATTACHMENTS}
                                            onClick={() => fileInputRef.current?.click()}
                                        >
                                            Anexar arquivo
                                        </Button>
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            multiple
                                            className="hidden"
                                            onChange={(e) => {
                                                void handleFiles(e.target.files);
                                                e.target.value = "";
                                            }}
                                        />

                                        {pendingAttachments.length > 0 && (
                                            <ul className="space-y-2">
                                                {pendingAttachments.map((attachment) => (
                                                    <li
                                                        key={attachment.key}
                                                        className="flex items-center gap-3 rounded-md border border-subtle bg-surface-2 px-3 py-2"
                                                    >
                                                        {attachment.status === "uploading" ? (
                                                            <Loader2 className="size-4 shrink-0 animate-spin text-tertiary" />
                                                        ) : attachment.status === "error" ? (
                                                            <Paperclip className="size-4 shrink-0 text-danger-primary" />
                                                        ) : (
                                                            <FileText className="size-4 shrink-0 text-tertiary" />
                                                        )}
                                                        <div className="min-w-0 flex-1">
                                                            <p className="truncate text-13 text-primary">{attachment.name}</p>
                                                            <p className="text-11 text-tertiary">
                                                                {attachment.status === "error"
                                                                    ? "Falha no envio"
                                                                    : attachment.status === "uploading"
                                                                        ? "Enviando…"
                                                                        : formatFileSize(attachment.size)}
                                                            </p>
                                                        </div>
                                                        <button
                                                            type="button"
                                                            aria-label={`Remover ${attachment.name}`}
                                                            className="rounded-sm p-1 text-tertiary transition-colors hover:bg-layer-1 hover:text-primary"
                                                            onClick={() => handleRemovePending(attachment.key)}
                                                        >
                                                            <X className="size-4" />
                                                        </button>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                )}

                                {formError && (
                                    <p className="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-13 text-danger-primary">
                                        {formError}
                                    </p>
                                )}

                                <div className="flex justify-end">
                                    <Button
                                        variant="primary"
                                        loading={isSubmitting}
                                        disabled={isUploading}
                                        prependIcon={<Send />}
                                        onClick={() => void handleSubmit()}
                                    >
                                        Enviar
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <PoweredBy />
        </>
    );
}
