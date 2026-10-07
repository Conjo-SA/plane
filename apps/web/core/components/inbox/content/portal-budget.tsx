/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CheckCircle2, Clock, Eye, Pencil, Plus, Send, XCircle } from "lucide-react";
import { observer } from "mobx-react";
import { useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { IntakePortalService } from "@plane/services";
import type { TIntakePortalBudget } from "@plane/types";
import { Input, TextArea } from "@plane/ui";
import { cn } from "@plane/utils";
// components
import { getIssueTimeSWRKey } from "@/components/issues/issue-detail-widgets/time";
// local imports
import { BudgetNote } from "./budget-note";

const intakePortalService = new IntakePortalService();

export const getPortalBudgetSWRKey = (issueId: string) => `PORTAL_BUDGET_${issueId}`;

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
  className?: string;
};

const formatDateTime = (value: string) =>
  new Date(value).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

const formatHours = (hours: number) => `${Number(hours).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}h`;

const STATUS = {
  APPROVED: {
    label: "Aprovado",
    icon: CheckCircle2,
    tone: "border-success-subtle bg-success-subtle",
    iconTone: "text-success-primary",
  },
  REJECTED: {
    label: "Recusado",
    icon: XCircle,
    tone: "border-danger-subtle bg-danger-subtle",
    iconTone: "text-danger-primary",
  },
  PENDING: {
    label: "Aguardando o cliente",
    icon: Clock,
    tone: "border-subtle bg-surface-2",
    iconTone: "text-tertiary",
  },
} as const;

function BudgetItem(props: { budget: TIntakePortalBudget; index: number }) {
  const { budget, index } = props;
  const status = STATUS[budget.status];
  const Icon = status.icon;
  const when =
    budget.status === "APPROVED" && budget.approved_at
      ? `por ${budget.approved_by_email} em ${formatDateTime(budget.approved_at)}`
      : budget.status === "REJECTED" && budget.rejected_at
        ? `por ${budget.rejected_by_email} em ${formatDateTime(budget.rejected_at)}`
        : budget.requested_at
          ? `enviado em ${formatDateTime(budget.requested_at)}`
          : "";

  return (
    <li className={cn("flex gap-3 rounded-md border px-3 py-2.5", status.tone)}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", status.iconTone)} />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="flex flex-wrap items-baseline gap-x-2 text-13">
          <span className="font-semibold text-primary">{formatHours(budget.estimated_hours)}</span>
          <span className="text-12 text-secondary">
            {index > 0 ? `Orçamento ${index + 1} · ` : ""}
            {status.label}
          </span>
          {when && <span className="text-11 text-tertiary">{when}</span>}
        </p>
        {budget.note && <BudgetNote text={budget.note} />}
        {budget.status === "REJECTED" && budget.rejection_reason && (
          <p className="text-12 text-secondary">
            <span className="font-medium text-primary">Motivo da recusa:</span> {budget.rejection_reason}
          </p>
        )}
      </div>
    </li>
  );
}

/** Estimates of a portal ticket: history, approved total and the form to send a new one (or revise the pending). */
export const IntakePortalBudgetRoot = observer(function IntakePortalBudgetRoot(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false, className } = props;
  // states
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");
  const [isPreview, setIsPreview] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // budget
  const { data, mutate } = useSWR(getPortalBudgetSWRKey(issueId), () =>
    intakePortalService.retrieveBudget(workspaceSlug, projectId, issueId)
  );

  const budgets = data?.budgets ?? (data?.budget ? [data.budget] : []);
  const pending = budgets.find((budget) => budget.status === "PENDING") ?? null;
  const approvedHours = data?.approved_hours ?? 0;
  const approvedCount = budgets.filter((budget) => budget.status === "APPROVED").length;
  const last = budgets[budgets.length - 1] ?? null;

  const openForm = (revise: boolean) => {
    setFormError(null);
    setIsPreview(false);
    setHours(revise && pending ? String(pending.estimated_hours) : "");
    setNote(revise && pending ? pending.note : "");
    setIsFormOpen(true);
  };

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
      setIsFormOpen(false);
      await mutate();
      void globalMutate(getIssueTimeSWRKey(issueId));
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

  const formTitle = pending
    ? "Revisar o orçamento pendente"
    : approvedCount > 0
      ? "Orçamento adicional"
      : last?.status === "REJECTED"
        ? "Novo orçamento"
        : "Enviar orçamento";
  const formHint = pending
    ? "O cliente recebe o valor revisado por e-mail. O orçamento continua aguardando a resposta dele."
    : approvedCount > 0
      ? `Para escopo novo. As ${formatHours(approvedHours)} já aprovadas não mudam; este orçamento é aprovado à parte e soma ao total.`
      : last?.status === "REJECTED"
        ? "O cliente recusou o orçamento anterior. Envie um novo valor para ele responder."
        : "O cliente recebe um e-mail e responde pelo portal. A aprovação é definitiva.";

  return (
    <div className={cn("relative space-y-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-body-sm-medium">Orçamento por hora</h3>
        {approvedCount > 0 && (
          <span className="text-12 text-secondary">
            Aprovado: <span className="font-semibold text-primary">{formatHours(approvedHours)}</span>
            {approvedCount > 1 && ` em ${approvedCount} orçamentos`}
          </span>
        )}
      </div>

      {budgets.length > 0 && (
        <ol className="space-y-2">
          {budgets.map((budget, index) => (
            <BudgetItem key={budget.id} budget={budget} index={index} />
          ))}
        </ol>
      )}

      {!disabled && !isFormOpen && (
        <div className="flex flex-wrap gap-2">
          {pending ? (
            <Button variant="secondary" size="sm" prependIcon={<Pencil />} onClick={() => openForm(true)}>
              Revisar orçamento pendente
            </Button>
          ) : budgets.length === 0 ? (
            <Button variant="primary" size="sm" prependIcon={<Send />} onClick={() => openForm(false)}>
              Enviar orçamento
            </Button>
          ) : (
            <Button variant="secondary" size="sm" prependIcon={<Plus />} onClick={() => openForm(false)}>
              {approvedCount > 0 ? "Orçamento adicional" : "Novo orçamento"}
            </Button>
          )}
        </div>
      )}

      {!disabled && isFormOpen && (
        <div className="space-y-2.5 rounded-md border border-subtle p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-13 font-medium text-primary">{formTitle}</span>
            <button
              type="button"
              className="flex items-center gap-1 text-12 text-secondary hover:text-primary"
              onClick={() => setIsPreview((value) => !value)}
            >
              {isPreview ? <Pencil className="size-3" /> : <Eye className="size-3" />}
              {isPreview ? "Editar" : "Pré-visualizar"}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min="0"
              step="0.25"
              className="w-32"
              placeholder="Horas"
              value={hours}
              onChange={(e) => setHours(e.target.value)}
            />
            <span className="text-12 text-tertiary">horas</span>
          </div>
          {isPreview ? (
            <div className="min-h-24 rounded-md border border-subtle bg-surface-2 px-3 py-2">
              {note.trim() ? (
                <BudgetNote text={note} />
              ) : (
                <span className="text-12 text-placeholder">Sem justificativa.</span>
              )}
            </div>
          ) : (
            <TextArea
              className="min-h-24 w-full resize-y text-13"
              placeholder={"Justificativa para o cliente (opcional)\nEx.:\n- Tela de cadastro\n- Ajuste no relatório"}
              value={note}
              maxLength={2000}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
          <p className="text-11 text-tertiary">
            Formatação: linhas com <code className="rounded-sm bg-layer-1 px-1">-</code> viram lista,{" "}
            <code className="rounded-sm bg-layer-1 px-1">1.</code> numera,{" "}
            <code className="rounded-sm bg-layer-1 px-1">**texto**</code> fica em negrito e linha em branco separa
            parágrafos.
          </p>
          <p className="text-11 text-tertiary">{formHint}</p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setIsFormOpen(false)} disabled={isSubmitting}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={isSubmitting}
              prependIcon={<Send />}
              onClick={() => void handleSubmit()}
            >
              {pending ? "Enviar revisão" : "Enviar ao cliente"}
            </Button>
          </div>
        </div>
      )}

      {formError && (
        <p className="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-12 text-danger-primary">
          {formError}
        </p>
      )}
    </div>
  );
});
