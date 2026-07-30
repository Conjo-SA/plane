/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CheckCircle2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
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

const intakePortalService = new IntakePortalService();

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

export default function IntakePortalPage() {
    // params
    const { anchor } = useParams<{ anchor: string }>();
    // states
    const [submittedMessage, setSubmittedMessage] = useState<string | null>(null);
    const [submitError, setSubmitError] = useState<string | null>(null);
    // refs
    const editorRef = useRef<EditorRefApi>(null);
    // form
    const {
        control,
        handleSubmit,
        register,
        reset,
        formState: { errors, isSubmitting },
    } = useForm<TIntakePortalSubmission>({ defaultValues: DEFAULT_VALUES });
    // portal meta
    const {
        data: portal,
        error,
        isLoading,
    } = useSWR(anchor ? `INTAKE_PORTAL_${anchor}` : null, anchor ? () => intakePortalService.retrieveMeta(anchor) : null);

    const onSubmit = async (formData: TIntakePortalSubmission) => {
        if (!anchor) return;
        setSubmitError(null);
        try {
            const response = await intakePortalService.createWorkItem(anchor, formData);
            setSubmittedMessage(response.success_message || "Recebemos sua solicitação. Em breve entraremos em contato.");
            reset(DEFAULT_VALUES);
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

    return (
        <>
            <div className="min-h-screen w-full overflow-y-auto bg-surface-2 py-10">
                <div className="mx-auto w-full max-w-2xl px-4">
                    <div className="rounded-lg border border-subtle bg-surface-1 p-6">
                        <h1 className="text-24 font-semibold text-primary">{portal.title}</h1>
                        <p className="mt-1 text-13 text-tertiary">
                            {portal.workspace_name} · {portal.project_name}
                        </p>
                        {portal.description && <p className="mt-4 text-14 text-secondary">{portal.description}</p>}

                        {submittedMessage ? (
                            <div className="mt-8 flex flex-col items-center gap-4 rounded-md border border-subtle bg-surface-2 p-8 text-center">
                                <CheckCircle2 className="size-10 text-success-primary" />
                                <p className="text-14 text-secondary">{submittedMessage}</p>
                                <Button variant="secondary" onClick={() => setSubmittedMessage(null)}>
                                    Abrir outra solicitação
                                </Button>
                            </div>
                        ) : (
                            <form className="mt-8 space-y-5" onSubmit={handleSubmit(onSubmit)}>
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
                                                containerClassName="min-h-[160px] rounded-md border border-subtle bg-surface-1 p-3"
                                                uploadFile={async () => {
                                                    throw new Error("Anexos não estão habilitados neste formulário.");
                                                }}
                                            />
                                        )}
                                    />
                                </div>

                                {submitError && (
                                    <p className="rounded-md bg-danger-subtle px-3 py-2 text-13 text-danger-primary">{submitError}</p>
                                )}

                                <div className="flex justify-end">
                                    <Button type="submit" variant="primary" loading={isSubmitting}>
                                        {isSubmitting ? "Enviando" : "Enviar solicitação"}
                                    </Button>
                                </div>
                            </form>
                        )}
                    </div>
                </div>
            </div>
            <PoweredBy />
        </>
    );
}
