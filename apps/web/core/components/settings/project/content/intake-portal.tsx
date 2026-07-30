/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Copy, RefreshCw, Tag } from "lucide-react";
import { observer } from "mobx-react";
import { useState } from "react";
import useSWR from "swr";
// plane imports
import { SITES_URL } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { IntakePortalService } from "@plane/services";
import type { TIntakePortal } from "@plane/types";
import { Input, TextArea, ToggleSwitch } from "@plane/ui";
// hooks
import { useLabel } from "@/hooks/store/use-label";

const intakePortalService = new IntakePortalService();

type Props = {
    projectId: string;
    workspaceSlug: string;
};

const isPortalConfigured = (portal: TIntakePortal | Record<string, never> | undefined): portal is TIntakePortal =>
    !!portal && "anchor" in portal;

/**
 * SITES_URL is relative (e.g. "/spaces") on self-hosted setups behind the bundled proxy,
 * so it is resolved against the current origin to produce a shareable, copy-pasteable link.
 */
const buildPortalUrl = (anchor: string): string => {
    const path = `${SITES_URL}/intake/${anchor}`;
    if (typeof window === "undefined") return path;
    try {
        return new URL(path, window.location.origin).toString();
    } catch {
        return path;
    }
};

/**
 * Builds the tagged variant of the portal link. Spaces become hyphens because the
 * API accepts hyphen/underscore separators, and the name is encoded so accented
 * labels stay valid in a URL.
 */
const buildTaggedPortalUrl = (portalUrl: string, labelName: string): string =>
    `${portalUrl}/${encodeURIComponent(labelName.trim().replace(/\s+/g, "-"))}`;

export const IntakePortalSettings = observer(function IntakePortalSettings(props: Props) {
    const { projectId, workspaceSlug } = props;
    // states
    const [title, setTitle] = useState<string | null>(null);
    const [description, setDescription] = useState<string | null>(null);
    const [successMessage, setSuccessMessage] = useState<string | null>(null);
    const [isSaving, setIsSaving] = useState(false);
    // store hooks
    const { getProjectLabels, fetchProjectLabels } = useLabel();
    // portal config
    const swrKey = `INTAKE_PORTAL_CONFIG_${workspaceSlug}_${projectId}`;
    const { data: portal, mutate } = useSWR(swrKey, () =>
        intakePortalService.retrieveConfig(workspaceSlug, projectId)
    );
    // project labels
    useSWR(
        workspaceSlug && projectId ? `PROJECT_LABELS_${workspaceSlug}_${projectId}` : null,
        workspaceSlug && projectId ? () => fetchProjectLabels(workspaceSlug, projectId) : null
    );
    const projectLabels = getProjectLabels(projectId) ?? [];

    const isConfigured = isPortalConfigured(portal);
    const portalUrl = isConfigured ? buildPortalUrl(portal.anchor) : "";

    const handleError = (fallback: string) =>
        setToast({ type: TOAST_TYPE.ERROR, title: "Erro!", message: fallback });

    const handleCreate = async () => {
        setIsSaving(true);
        try {
            const response = await intakePortalService.createConfig(workspaceSlug, projectId, { is_enabled: true });
            await mutate(response, false);
            setToast({ type: TOAST_TYPE.SUCCESS, title: "Sucesso!", message: "Formulário público criado." });
        } catch {
            handleError("Ative o Intake do projeto antes de criar o formulário público.");
        } finally {
            setIsSaving(false);
        }
    };

    const handleUpdate = async (payload: Partial<TIntakePortal> & { regenerate_anchor?: boolean }) => {
        setIsSaving(true);
        try {
            const response = await intakePortalService.updateConfig(workspaceSlug, projectId, payload);
            await mutate(response, false);
            setToast({ type: TOAST_TYPE.SUCCESS, title: "Sucesso!", message: "Formulário atualizado." });
        } catch {
            handleError("Não foi possível atualizar o formulário. Tente novamente.");
        } finally {
            setIsSaving(false);
        }
    };

    const handleCopyLink = async () => {
        try {
            await navigator.clipboard.writeText(portalUrl);
            setToast({ type: TOAST_TYPE.SUCCESS, title: "Copiado!", message: "Link copiado para a área de transferência." });
        } catch {
            handleError("Não foi possível copiar o link.");
        }
    };

    const handleCopyTaggedLink = async (labelName: string) => {
        try {
            await navigator.clipboard.writeText(buildTaggedPortalUrl(portalUrl, labelName));
            setToast({
                type: TOAST_TYPE.SUCCESS,
                title: "Copiado!",
                message: `Link da etiqueta "${labelName}" copiado.`,
            });
        } catch {
            handleError("Não foi possível copiar o link.");
        }
    };

    if (!isConfigured)
        return (
            <div className="mt-4 rounded-md border border-subtle p-4">
                <h4 className="text-14 font-medium text-primary">Formulário público de chamados</h4>
                <p className="mt-1 text-13 text-tertiary">
                    Gere um link para que clientes externos abram chamados sem precisar de conta no Plane. As solicitações caem no
                    Intake do projeto.
                </p>
                <Button className="mt-4" variant="primary" size="sm" loading={isSaving} onClick={() => void handleCreate()}>
                    Criar formulário público
                </Button>
            </div>
        );

    return (
        <div className="mt-4 space-y-4 rounded-md border border-subtle p-4">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h4 className="text-14 font-medium text-primary">Formulário público de chamados</h4>
                    <p className="mt-1 text-13 text-tertiary">
                        Quando desativado, o link deixa de responder e ninguém consegue enviar novas solicitações.
                    </p>
                </div>
                <ToggleSwitch
                    value={portal.is_enabled}
                    onChange={() => void handleUpdate({ is_enabled: !portal.is_enabled })}
                    disabled={isSaving}
                    size="sm"
                />
            </div>

            <div className="flex items-start justify-between gap-4 border-t border-subtle-1 pt-4">
                <div>
                    <h4 className="text-14 font-medium text-primary">Permitir anexos</h4>
                    <p className="mt-1 text-13 text-tertiary">
                        Habilita o envio de imagens, vídeos, PDFs, planilhas e arquivos ZIP junto do chamado.
                    </p>
                </div>
                <ToggleSwitch
                    value={portal.is_attachment_enabled}
                    onChange={() => void handleUpdate({ is_attachment_enabled: !portal.is_attachment_enabled })}
                    disabled={isSaving}
                    size="sm"
                />
            </div>

            <div className="space-y-1">
                <span className="text-13 font-medium text-secondary">Link público</span>
                <div className="flex items-center gap-2">
                    <Input type="text" className="w-full" value={portalUrl} readOnly />
                    <Button variant="secondary" size="sm" onClick={() => void handleCopyLink()} prependIcon={<Copy />}>
                        Copiar
                    </Button>
                    <Button
                        variant="secondary"
                        size="sm"
                        disabled={isSaving}
                        onClick={() => void handleUpdate({ regenerate_anchor: true })}
                        prependIcon={<RefreshCw />}
                    >
                        Gerar novo
                    </Button>
                </div>
                <p className="text-11 text-tertiary">Gerar um novo link invalida imediatamente o link anterior.</p>
            </div>

            <div className="space-y-2 border-t border-subtle-1 pt-4">
                <div>
                    <h4 className="text-14 font-medium text-primary">Links por etiqueta</h4>
                    <p className="mt-1 text-13 text-tertiary">
                        Divulgue um link por canal. Os chamados abertos por ele já entram no Intake com a etiqueta
                        aplicada.
                    </p>
                </div>

                {projectLabels.length === 0 ? (
                    <p className="rounded-md border border-dashed border-subtle px-3 py-4 text-13 text-tertiary">
                        Este projeto ainda não tem etiquetas. Crie etiquetas nas configurações do projeto para gerar
                        links classificados.
                    </p>
                ) : (
                    <ul className="divide-y divide-subtle-1 overflow-hidden rounded-md border border-subtle">
                        {projectLabels.map((label) => (
                            <li key={label.id} className="flex items-center gap-3 px-3 py-2">
                                <span
                                    aria-hidden
                                    className="size-2.5 shrink-0 rounded-full"
                                    style={{ backgroundColor: label.color || "#6b7280" }}
                                />
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-13 font-medium text-primary">{label.name}</p>
                                    <p className="truncate font-mono text-11 text-tertiary">
                                        {buildTaggedPortalUrl(portalUrl, label.name)}
                                    </p>
                                </div>
                                <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={() => void handleCopyTaggedLink(label.name)}
                                    prependIcon={<Tag />}
                                >
                                    Copiar
                                </Button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>

            <div className="space-y-1">
                <label className="text-13 font-medium text-secondary" htmlFor="intake-portal-title">
                    Título da página
                </label>
                <Input
                    id="intake-portal-title"
                    type="text"
                    className="w-full"
                    placeholder="Abrir um chamado"
                    value={title ?? portal.title}
                    onChange={(e) => setTitle(e.target.value)}
                />
            </div>

            <div className="space-y-1">
                <label className="text-13 font-medium text-secondary" htmlFor="intake-portal-description">
                    Texto de apresentação
                </label>
                <TextArea
                    id="intake-portal-description"
                    className="w-full"
                    rows={3}
                    placeholder="Explique ao cliente o que informar e qual o prazo de retorno."
                    value={description ?? portal.description}
                    onChange={(e) => setDescription(e.target.value)}
                />
            </div>

            <div className="space-y-1">
                <label className="text-13 font-medium text-secondary" htmlFor="intake-portal-success">
                    Mensagem de confirmação
                </label>
                <TextArea
                    id="intake-portal-success"
                    className="w-full"
                    rows={2}
                    placeholder="Recebemos sua solicitação e responderemos em até 1 dia útil."
                    value={successMessage ?? portal.success_message}
                    onChange={(e) => setSuccessMessage(e.target.value)}
                />
            </div>

            <div className="flex justify-end">
                <Button
                    variant="primary"
                    size="sm"
                    loading={isSaving}
                    onClick={() =>
                        void handleUpdate({
                            title: title ?? portal.title,
                            description: description ?? portal.description,
                            success_message: successMessage ?? portal.success_message,
                        })
                    }
                >
                    Salvar alterações
                </Button>
            </div>
        </div>
    );
});
