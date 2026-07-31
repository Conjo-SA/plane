/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CheckCircle2, Clock, Send } from "lucide-react";
import { observer } from "mobx-react";
import { useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { IntakePortalService } from "@plane/services";
import { Input } from "@plane/ui";

const intakePortalService = new IntakePortalService();

type Props = {
    workspaceSlug: string;
    projectId: string;
    issueId: string;
    disabled?: boolean;
};

const formatDateTime = (value: string) => new Date(value).toLocaleString("pt-BR");

export const IntakePortalBudgetRoot = observer(function IntakePortalBudgetRoot(props: Props) {
    const { workspaceSlug, projectId, issueId, disabled = false } = props;
    // states
    const [hours, setHours] = useState("");
    const [note, setNote] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    // budget
    const { data, mutate } = useSWR(`PORTAL_BUDGET_${issueId}`, () =>
        intakePortalService.retrieveBudget(workspaceSlug, projectId, issueId)
    );

    const budget = data?.budget ?? null;
    const isApproved = budget?.is_approved ?? false;

    const handleSubmit = async () => {
        setFormError(null);

        const parsedHours = Number(hours.replace(",", "."));
        if (!Number.isFinite(parsedHours) || parsedHours <= 0) {
            setFormError("Informe um número de horas maior que zero.");
            return;
        }

        setIsSubmitting(true);
        try {
            await intakePortalService.requestBudgetApproval(workspaceSlug, projectId, issueId, {
                estimated_hours: parsedHours,
                note: note.trim(),
            });
            setHours("");
            setNote("");
            await mutate();
        } catch (error) {
            const message = (error as { data?: { error?: string } })?.data?.error;
            setFormError(message || "Não foi possível enviar o orçamento. Tente novamente.");
        } finally {
            setIsSubmitting(false);
        }
    };

    // Only tickets that came from the portal have a requester who can approve one.
    // Kept hidden while loading so the form never flashes on a regular work item.
    if (!data?.is_portal_ticket) return null;

    return (
        <div className="relative space-y-3">
            <h3 className="text-body-sm-medium">Orçamento por hora</h3>
            {budget && (
                <div
                    className={`flex flex-wrap items-center gap-3 rounded-md border px-3 py-2.5 ${isApproved ? "border-success-subtle bg-success-subtle" : "border-subtle bg-surface-2"
                        }`}
                >
                    {isApproved ? (
                        <CheckCircle2 className="size-4 shrink-0 text-success-primary" />
                    ) : (
                        <Clock className="size-4 shrink-0 text-tertiary" />
                    )}
                    <div className="min-w-0 flex-1">
                        <p className="text-13 font-medium text-primary">{budget.estimated_hours} horas</p>
                        <p className="text-11 text-tertiary">
                            {isApproved && budget.approved_at
                                ? `Aprovado por ${budget.approved_by_email} em ${formatDateTime(budget.approved_at)}`
                                : budget.requested_at
                                    ? `Aguardando aprovação do cliente desde ${formatDateTime(budget.requested_at)}`
                                    : "Aguardando aprovação do cliente"}
                        </p>
                        {budget.note && <p className="mt-1 text-12 text-secondary">{budget.note}</p>}
                    </div>
                </div>
            )}

            {isApproved ? (
                <p className="text-11 text-tertiary">
                    O cliente já aprovou este orçamento. A aprovação é definitiva e o valor não pode mais ser alterado.
                </p>
            ) : (
                !disabled && (
                    <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <Input
                                type="number"
                                min="0"
                                step="0.25"
                                className="w-32"
                                placeholder="Horas"
                                value={hours}
                                onChange={(e) => setHours(e.target.value)}
                            />
                            <Input
                                type="text"
                                className="min-w-[200px] flex-1"
                                placeholder="Observação para o cliente (opcional)"
                                value={note}
                                onChange={(e) => setNote(e.target.value)}
                            />
                            <Button
                                variant="primary"
                                size="sm"
                                loading={isSubmitting}
                                prependIcon={<Send />}
                                onClick={() => void handleSubmit()}
                            >
                                {budget ? "Reenviar" : "Enviar"}
                            </Button>
                        </div>
                        <p className="text-11 text-tertiary">
                            O cliente recebe um e-mail e aprova pelo portal. Só ele pode aprovar, e apenas uma vez.
                        </p>
                    </div>
                )
            )}

            {formError && (
                <p className="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-12 text-danger-primary">
                    {formError}
                </p>
            )}
        </div>
    );
});
