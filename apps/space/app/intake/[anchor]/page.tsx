/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CheckCircle2, CloudUpload, FileText, Loader2, MailCheck, Paperclip, ShieldCheck, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import type { EditorRefApi } from "@plane/editor";
import { Button } from "@plane/propel/button";
import { IntakePortalService } from "@plane/services";
import type { TIntakePortalSubmission } from "@plane/types";
import { Input } from "@plane/ui";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PoweredBy } from "@/components/common/powered-by";
import { RichTextEditor } from "@/components/editor/rich-text-editor";
import { PageNotFound } from "@/components/ui/not-found";
// helpers
import { getPortalSession, setPortalSession } from "@/helpers/portal-session";

const intakePortalService = new IntakePortalService();

const MAX_ATTACHMENTS = 10;

const PRIORITY_OPTIONS: { value: TIntakePortalSubmission["priority"]; label: string }[] = [
    { value: "none", label: "Sem prioridade" },
    { value: "low", label: "Baixa" },
    { value: "medium", label: "Média" },
    { value: "high", label: "Alta" },
    { value: "urgent", label: "Urgente" },
];

const DEFAULT_VALUES: TIntakePortalSubmission = {
    name: "",
    description_html: "<p></p>",
    priority: "none",
    requester_name: "",
    requester_email: "",
};

type TAttachment = {
    key: string;
    name: string;
    size: number;
    assetId?: string;
    status: "uploading" | "done" | "error";
};

const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function IntakePortalPage() {
    // params
    const { anchor, tag } = useParams<{ anchor: string; tag?: string }>();
    // states
    const [submittedMessage, setSubmittedMessage] = useState<string | null>(null);
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [attachments, setAttachments] = useState<TAttachment[]>([]);
    const [isDragging, setIsDragging] = useState(false);
    const [session, setSession] = useState(() => (anchor ? getPortalSession(anchor) : null));
    const [verificationCode, setVerificationCode] = useState("");
    const [isCodeSent, setIsCodeSent] = useState(false);
    const [sentToEmail, setSentToEmail] = useState<string | null>(null);
    const [isVerifying, setIsVerifying] = useState(false);
    // refs
    const editorRef = useRef<EditorRefApi>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    // form
    const {
        control,
        handleSubmit,
        register,
        reset,
        watch,
        formState: { errors, isSubmitting },
    } = useForm<TIntakePortalSubmission>({ defaultValues: DEFAULT_VALUES });
    // portal meta
    const {
        data: portal,
        error,
        isLoading,
    } = useSWR(
        anchor ? `INTAKE_PORTAL_${anchor}_${tag ?? ""}` : null,
        anchor ? () => intakePortalService.retrieveMeta(anchor, tag) : null
    );

    const isUploading = attachments.some((attachment) => attachment.status === "uploading");

    const handleFiles = async (files: FileList | null) => {
        if (!files || !anchor) return;
        setSubmitError(null);

        const incoming = Array.from(files).slice(0, MAX_ATTACHMENTS - attachments.length);
        if (incoming.length === 0) {
            setSubmitError(`Você pode anexar no máximo ${MAX_ATTACHMENTS} arquivos.`);
            return;
        }

        for (const file of incoming) {
            const key = `${file.name}-${file.size}-${Date.now()}-${Math.random()}`;
            setAttachments((prev) => [...prev, { key, name: file.name, size: file.size, status: "uploading" }]);

            try {
                const assetId = await intakePortalService.uploadAsset(anchor, file);
                setAttachments((prev) =>
                    prev.map((item) => (item.key === key ? { ...item, assetId, status: "done" } : item))
                );
            } catch (err) {
                const message = (err as { data?: { error?: string } })?.data?.error;
                setSubmitError(message || `Não foi possível enviar o arquivo "${file.name}".`);
                setAttachments((prev) => prev.map((item) => (item.key === key ? { ...item, status: "error" } : item)));
            }
        }
    };

    const handleRemoveAttachment = (key: string) =>
        setAttachments((prev) => prev.filter((attachment) => attachment.key !== key));

    const handleRequestCode = async (rawEmail: string) => {
        const emailValue = (rawEmail || "").trim().toLowerCase();
        if (!anchor || !emailValue) return;
        setSubmitError(null);
        setIsVerifying(true);
        try {
            await intakePortalService.requestVerificationCode(anchor, emailValue);
            setSentToEmail(emailValue);
            setIsCodeSent(true);
        } catch (err) {
            const message = (err as { data?: { error?: string } })?.data?.error;
            setSubmitError(message || "Não foi possível enviar o código. Tente novamente.");
        } finally {
            setIsVerifying(false);
        }
    };

    const handleConfirmCode = async (rawEmail: string) => {
        const emailValue = (rawEmail || "").trim().toLowerCase();
        if (!anchor || !emailValue) return;
        setSubmitError(null);
        setIsVerifying(true);
        try {
            const response = await intakePortalService.confirmVerificationCode(anchor, emailValue, verificationCode);
            setPortalSession(anchor, response);
            setSession(response);
            setVerificationCode("");
            setIsCodeSent(false);
        } catch (err) {
            const message = (err as { data?: { error?: string } })?.data?.error;
            setSubmitError(message || "Código inválido. Tente novamente.");
        } finally {
            setIsVerifying(false);
        }
    };

    const onSubmit = async (formData: TIntakePortalSubmission) => {
        if (!anchor) return;
        setSubmitError(null);

        if (isUploading) {
            setSubmitError("Aguarde o envio dos anexos terminar.");
            return;
        }

        if (!session || session.email.toLowerCase() !== formData.requester_email.trim().toLowerCase()) {
            setSubmitError("Confirme seu e-mail antes de enviar a solicitação.");
            return;
        }

        try {
            const response = await intakePortalService.createWorkItem(
                anchor,
                {
                    ...formData,
                    tag,
                    attachment_ids: attachments
                        .filter((attachment) => attachment.status === "done" && attachment.assetId)
                        .map((attachment) => attachment.assetId as string),
                },
                session.token
            );
            setSubmittedMessage(response.success_message || "Recebemos sua solicitação. Em breve entraremos em contato.");
            reset(DEFAULT_VALUES);
            setAttachments([]);
            editorRef.current?.clearEditor();
        } catch (err) {
            const message = (err as { data?: { error?: string } })?.data?.error;
            setSubmitError(message || "Não foi possível enviar sua solicitação. Tente novamente.");
        }
    };

    if (isLoading)
        return (
            <div className="flex h-screen w-full items-center justify-center bg-surface-1">
                <LogoSpinner />
            </div>
        );

    if (error || !portal) return <PageNotFound />;

    const projectInitial = portal.project_name?.charAt(0)?.toUpperCase() ?? "?";

    return (
        <>
            <div className="min-h-screen w-full overflow-y-auto bg-gradient-to-b from-surface-2 via-surface-2 to-surface-1">
                <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:py-14">
                    <div className="overflow-hidden rounded-2xl border border-subtle bg-surface-1 shadow-raised-200">
                        <div className="border-b border-subtle-1 bg-gradient-to-r from-accent-subtle to-surface-1 px-6 py-7 sm:px-9">
                            <div className="flex items-start gap-4">
                                <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-accent-primary text-18 font-semibold text-white">
                                    {projectInitial}
                                </div>
                                <div className="min-w-0 flex-1">
                                    <p className="text-11 font-medium tracking-wide text-tertiary uppercase">
                                        {portal.workspace_name} · {portal.project_name}
                                    </p>
                                    <h1 className="mt-1 text-24 leading-tight font-semibold text-primary">{portal.title}</h1>
                                    {portal.tag && (
                                        <span
                                            className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-subtle bg-surface-1 px-2.5 py-1 text-12 font-medium text-secondary"
                                            title={`Esta solicitação será marcada como "${portal.tag.name}"`}
                                        >
                                            <span
                                                aria-hidden
                                                className="size-2 shrink-0 rounded-full"
                                                style={{ backgroundColor: portal.tag.color || "#6b7280" }}
                                            />
                                            {portal.tag.name}
                                        </span>
                                    )}
                                </div>
                            </div>
                            {portal.description && (
                                <p className="mt-5 text-14 leading-relaxed text-secondary">{portal.description}</p>
                            )}
                        </div>

                        <div className="px-6 py-7 sm:px-9">
                            {submittedMessage ? (
                                <div className="flex flex-col items-center gap-4 py-10 text-center">
                                    <div className="flex size-16 items-center justify-center rounded-full bg-success-subtle">
                                        <CheckCircle2 className="size-8 text-success-primary" />
                                    </div>
                                    <div>
                                        <h2 className="text-18 font-semibold text-primary">Solicitação enviada</h2>
                                        <p className="mt-2 max-w-md text-14 text-secondary">{submittedMessage}</p>
                                    </div>
                                    <div className="flex flex-wrap items-center justify-center gap-2">
                                        <Button variant="secondary" onClick={() => setSubmittedMessage(null)}>
                                            Abrir outra solicitação
                                        </Button>
                                        <Link
                                            to={`/portal/${anchor}`}
                                            className="rounded-md px-3 py-2 text-13 font-medium text-accent-primary hover:underline"
                                        >
                                            Acompanhar meus chamados
                                        </Link>
                                    </div>
                                </div>
                            ) : (
                                <form className="space-y-6" onSubmit={handleSubmit(onSubmit)}>
                                    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                                        <div className="space-y-1">
                                            <label className="text-13 font-medium text-secondary" htmlFor="requester_name">
                                                Seu nome <span className="text-danger-primary">*</span>
                                            </label>
                                            <Input
                                                id="requester_name"
                                                type="text"
                                                className="w-full"
                                                hasError={Boolean(errors.requester_name)}
                                                placeholder="Como podemos te chamar?"
                                                {...register("requester_name", { required: "Informe seu nome" })}
                                            />
                                            {errors.requester_name && (
                                                <p className="text-11 text-danger-primary">{errors.requester_name.message}</p>
                                            )}
                                        </div>

                                        <div className="space-y-1">
                                            <label className="text-13 font-medium text-secondary" htmlFor="requester_email">
                                                Seu e-mail <span className="text-danger-primary">*</span>
                                            </label>
                                            <Input
                                                id="requester_email"
                                                type="email"
                                                className="w-full"
                                                hasError={Boolean(errors.requester_email)}
                                                placeholder="voce@empresa.com"
                                                {...register("requester_email", {
                                                    required: "Informe seu e-mail",
                                                    pattern: {
                                                        value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
                                                        message: "Informe um e-mail válido",
                                                    },
                                                })}
                                            />
                                            {errors.requester_email && (
                                                <p className="text-11 text-danger-primary">{errors.requester_email.message}</p>
                                            )}
                                        </div>
                                    </div>

                                    {session ? (
                                        <p className="flex items-center gap-1.5 rounded-md border border-success-subtle bg-success-subtle px-3 py-2 text-12 text-success-primary">
                                            <CheckCircle2 className="size-3.5" />
                                            E-mail confirmado: {session.email}
                                        </p>
                                    ) : (
                                        <div className="space-y-2 rounded-md border border-subtle bg-surface-2 px-3 py-3">
                                            <p className="text-12 text-secondary">
                                                {isCodeSent && sentToEmail
                                                    ? `Enviamos um código de 6 dígitos para ${sentToEmail}. Verifique também a caixa de spam.`
                                                    : "Confirme seu e-mail para abrir o chamado e acompanhar as atualizações."}
                                            </p>
                                            {isCodeSent ? (
                                                <div className="flex flex-col gap-2 sm:flex-row">
                                                    <Input
                                                        type="text"
                                                        inputMode="numeric"
                                                        maxLength={6}
                                                        className="w-full sm:max-w-[160px]"
                                                        placeholder="000000"
                                                        value={verificationCode}
                                                        onChange={(e) => setVerificationCode(e.target.value)}
                                                    />
                                                    <Button
                                                        variant="primary"
                                                        size="sm"
                                                        loading={isVerifying}
                                                        disabled={verificationCode.length < 6}
                                                        onClick={() => void handleConfirmCode(watch("requester_email"))}
                                                    >
                                                        Confirmar código
                                                    </Button>
                                                    <Button
                                                        variant="secondary"
                                                        size="sm"
                                                        disabled={isVerifying}
                                                        onClick={() => void handleRequestCode(watch("requester_email"))}
                                                    >
                                                        Reenviar
                                                    </Button>
                                                </div>
                                            ) : (
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    loading={isVerifying}
                                                    disabled={!watch("requester_email")}
                                                    onClick={() => void handleRequestCode(watch("requester_email"))}
                                                    prependIcon={<MailCheck />}
                                                >
                                                    Enviar código de confirmação
                                                </Button>
                                            )}
                                        </div>
                                    )}

                                    <div className="space-y-1">
                                        <label className="text-13 font-medium text-secondary" htmlFor="name">
                                            Assunto <span className="text-danger-primary">*</span>
                                        </label>
                                        <Input
                                            id="name"
                                            type="text"
                                            className="w-full"
                                            hasError={Boolean(errors.name)}
                                            placeholder="Resuma sua solicitação em uma frase"
                                            {...register("name", {
                                                required: "Informe o assunto",
                                                maxLength: { value: 255, message: "O assunto deve ter no máximo 255 caracteres" },
                                            })}
                                        />
                                        {errors.name && <p className="text-11 text-danger-primary">{errors.name.message}</p>}
                                    </div>

                                    <div className="space-y-1">
                                        <label className="text-13 font-medium text-secondary" htmlFor="priority">
                                            Prioridade
                                        </label>
                                        <select
                                            id="priority"
                                            className="w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-14 text-primary outline-none focus:border-strong"
                                            {...register("priority")}
                                        >
                                            {PRIORITY_OPTIONS.map((option) => (
                                                <option key={option.value} value={option.value}>
                                                    {option.label}
                                                </option>
                                            ))}
                                        </select>
                                    </div>

                                    <div className="space-y-1">
                                        <span className="text-13 font-medium text-secondary">Descrição</span>
                                        <div className="rounded-md border border-subtle bg-surface-1 transition-colors focus-within:border-strong">
                                            <Controller
                                                name="description_html"
                                                control={control}
                                                render={({ field: { value, onChange } }) => (
                                                    <RichTextEditor
                                                        editable
                                                        id="intake-portal-editor"
                                                        ref={editorRef}
                                                        anchor={anchor}
                                                        workspaceId=""
                                                        initialValue={value ?? "<p></p>"}
                                                        onChange={(_description, description_html) => onChange(description_html)}
                                                        disabledExtensions={["ai", "image", "issue-embed"]}
                                                        placeholder="Descreva o problema, o passo a passo para reproduzir e o resultado esperado."
                                                        containerClassName="min-h-[180px] p-3"
                                                        uploadFile={async () => {
                                                            throw new Error("Use o campo de anexos abaixo para enviar arquivos.");
                                                        }}
                                                    />
                                                )}
                                            />
                                        </div>
                                        <p className="text-11 text-tertiary">
                                            Dica: você pode colar Markdown e blocos de código com três crases.
                                        </p>
                                    </div>

                                    {portal.is_attachment_enabled && (
                                        <div className="space-y-2">
                                            <span className="text-13 font-medium text-secondary">Anexos</span>
                                            <button
                                                type="button"
                                                onClick={() => fileInputRef.current?.click()}
                                                onDragOver={(e) => {
                                                    e.preventDefault();
                                                    setIsDragging(true);
                                                }}
                                                onDragLeave={() => setIsDragging(false)}
                                                onDrop={(e) => {
                                                    e.preventDefault();
                                                    setIsDragging(false);
                                                    void handleFiles(e.dataTransfer.files);
                                                }}
                                                className={`flex w-full flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center transition-colors ${isDragging
                                                    ? "border-accent-strong bg-accent-subtle"
                                                    : "border-subtle bg-surface-2 hover:border-strong hover:bg-layer-1"
                                                    }`}
                                            >
                                                <CloudUpload className="size-6 text-tertiary" />
                                                <span className="text-13 font-medium text-secondary">
                                                    Arraste arquivos aqui ou clique para selecionar
                                                </span>
                                                <span className="text-11 text-tertiary">
                                                    Imagens, vídeos, PDF, planilhas e arquivos ZIP · até {MAX_ATTACHMENTS} arquivos
                                                </span>
                                            </button>
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

                                            {attachments.length > 0 && (
                                                <ul className="space-y-2">
                                                    {attachments.map((attachment) => (
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
                                                                onClick={() => handleRemoveAttachment(attachment.key)}
                                                            >
                                                                <X className="size-4" />
                                                            </button>
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    )}

                                    {submitError && (
                                        <p className="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-13 text-danger-primary">
                                            {submitError}
                                        </p>
                                    )}

                                    <div className="flex flex-col-reverse items-center justify-between gap-3 border-t border-subtle-1 pt-5 sm:flex-row">
                                        <p className="flex items-center gap-1.5 text-11 text-tertiary">
                                            <ShieldCheck className="size-3.5" />
                                            Seus dados são usados apenas para responder esta solicitação.
                                        </p>
                                        <Button type="submit" variant="primary" size="lg" loading={isSubmitting} disabled={isUploading}>
                                            {isSubmitting ? "Enviando" : "Enviar solicitação"}
                                        </Button>
                                    </div>
                                </form>
                            )}
                        </div>
                    </div>
                </div>
            </div>
            <PoweredBy />
        </>
    );
}
