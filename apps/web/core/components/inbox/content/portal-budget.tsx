/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Ban, CheckCircle2, Clock, Eye, History, Pencil, Plus, Send, XCircle } from "lucide-react";
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
import { BudgetTimeline } from "./budget-timeline";

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
  CANCELLED: {
    label: "Cancelado",
    icon: Ban,
    tone: "border-subtle bg-layer-1",
    iconTone: "text-tertiary",
  },
} as const;

const readError = (error: unknown) => (error as { data?: { error?: string } })?.data?.error;

type BudgetItemProps = {
  budget: TIntakePortalBudget;
  index: number;
  onEdit?: () => void;
  /** Cancels this estimate (pending or rejected only); rejects with the API message on failure. */
  onCancel?: (reason: string) => Promise<void>;
};

function BudgetItem(props: BudgetItemProps) {
  const { budget, index, onEdit, onCancel } = props;
  const [showTimeline, setShowTimeline] = useState(budget.status === "PENDING" && (budget.revision_count ?? 0) > 0);
  const [isConfirmingCancel, setIsConfirmingCancel] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [isCancelling, setIsCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const handleConfirmCancel = async () => {
    if (!onCancel) return;
    setIsCancelling(true);
    setCancelError(null);
    try {
      await onCancel(cancelReason.trim());
      setIsConfirmingCancel(false);
      setCancelReason("");
    } catch (error) {
      setCancelError(readError(error) || "Não foi possível cancelar o orçamento. Tente novamente.");
    } finally {
      setIsCancelling(false);
    }
  };
  const events = budget.events ?? [];
  const status = STATUS[budget.status];
  const Icon = status.icon;
  const when =
    budget.status === "APPROVED" && budget.approved_at
      ? `por ${budget.approved_by_email} em ${formatDateTime(budget.approved_at)}`
      : budget.status === "REJECTED" && budget.rejected_at
        ? `por ${budget.rejected_by_email} em ${formatDateTime(budget.rejected_at)}`
        : budget.status === "CANCELLED" && budget.cancelled_at
          ? `por ${budget.cancelled_by ?? "Equipe"} em ${formatDateTime(budget.cancelled_at)}`
          : budget.requested_at
            ? `${(budget.revision_count ?? 0) > 0 ? "atualizado" : "enviado"} em ${formatDateTime(budget.requested_at)}`
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
          {(budget.revision_count ?? 0) > 0 && (
            <span className="text-11 text-tertiary">
              · alterado {budget.revision_count} {budget.revision_count === 1 ? "vez" : "vezes"}
            </span>
          )}
        </p>
        {budget.note && <BudgetNote text={budget.note} />}
        {budget.rejection_reason && (budget.status === "REJECTED" || budget.status === "CANCELLED") && (
          <p className="text-12 text-secondary">
            <span className="font-medium text-primary">Motivo da recusa:</span> {budget.rejection_reason}
          </p>
        )}
        {budget.status === "CANCELLED" && budget.cancellation_reason && (
          <p className="text-12 text-secondary">
            <span className="font-medium text-primary">Motivo do cancelamento:</span> {budget.cancellation_reason}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 pt-0.5">
          {onEdit && budget.can_edit !== false && (
            <button
              type="button"
              className="flex items-center gap-1 text-12 font-medium text-accent-primary hover:underline"
              onClick={onEdit}
            >
              <Pencil className="size-3" />
              Editar
            </button>
          )}
          {onCancel && budget.can_cancel && !isConfirmingCancel && (
            <button
              type="button"
              className="flex items-center gap-1 text-12 font-medium text-danger-primary hover:underline"
              onClick={() => {
                setCancelError(null);
                setIsConfirmingCancel(true);
              }}
            >
              <Ban className="size-3" />
              Cancelar orçamento
            </button>
          )}
          {events.length > 1 && (
            <button
              type="button"
              className="flex items-center gap-1 text-12 text-secondary hover:text-primary"
              onClick={() => setShowTimeline((value) => !value)}
            >
              <History className="size-3" />
              {showTimeline ? "Esconder histórico" : "Ver histórico"}
            </button>
          )}
        </div>
        {isConfirmingCancel && onCancel && (
          <div className="mt-1 space-y-2 rounded-md border border-danger-subtle bg-surface-1 p-2.5">
            <p className="text-12 text-secondary">
              {budget.status === "PENDING"
                ? "O cliente não poderá mais aprovar nem recusar este orçamento e recebe um e-mail avisando do cancelamento. Depois você pode enviar um novo."
                : "O orçamento recusado fica marcado como cancelado e o cliente recebe um e-mail avisando. Depois você pode enviar um novo."}
            </p>
            <TextArea
              className="min-h-16 w-full resize-y text-13"
              placeholder="Motivo do cancelamento para o cliente (opcional)"
              value={cancelReason}
              maxLength={1000}
              onChange={(e) => setCancelReason(e.target.value)}
            />
            {cancelError && <p className="text-12 text-danger-primary">{cancelError}</p>}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={isCancelling}
                onClick={() => {
                  setIsConfirmingCancel(false);
                  setCancelReason("");
                  setCancelError(null);
                }}
              >
                Voltar
              </Button>
              <Button
                variant="error-fill"
                size="sm"
                loading={isCancelling}
                prependIcon={<Ban />}
                onClick={() => void handleConfirmCancel()}
              >
                Confirmar cancelamento
              </Button>
            </div>
          </div>
        )}
        {showTimeline && <BudgetTimeline events={events} className="pt-1" />}
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
      setFormError(readError(error) || "Não foi possível enviar o orçamento. Tente novamente.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Throws the API error so the estimate shows it next to its confirmation.
  const handleCancel = async (budgetId: string, reason: string) => {
    await intakePortalService.cancelBudget(workspaceSlug, projectId, issueId, { budget_id: budgetId, reason });
    if (pending?.id === budgetId) setIsFormOpen(false);
    await mutate();
    void globalMutate(getIssueTimeSWRKey(issueId));
  };

  // Only tickets that came from the portal have a requester who can approve one.
  // Kept hidden while loading so the form never flashes on a regular work item.
  if (!data?.is_portal_ticket) return null;

  const formTitle = pending
    ? "Editar orçamento pendente"
    : approvedCount > 0
      ? "Orçamento adicional"
      : last?.status === "REJECTED" || last?.status === "CANCELLED"
        ? "Novo orçamento"
        : "Enviar orçamento";
  const formHint = pending
    ? "A alteração fica no histórico do orçamento (com o valor e a justificativa anteriores) e o cliente recebe o orçamento revisado por e-mail."
    : approvedCount > 0
      ? `Para escopo novo. As ${formatHours(approvedHours)} já aprovadas não mudam; este orçamento é aprovado à parte e soma ao total.`
      : last?.status === "REJECTED"
        ? "O cliente recusou o orçamento anterior. Envie um novo valor para ele responder."
        : last?.status === "CANCELLED"
          ? "O orçamento anterior foi cancelado. Envie um novo valor para o cliente responder."
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
            <BudgetItem
              key={budget.id}
              budget={budget}
              index={index}
              onEdit={!disabled && budget.status === "PENDING" ? () => openForm(true) : undefined}
              onCancel={!disabled && budget.can_cancel ? (reason) => handleCancel(budget.id, reason) : undefined}
            />
          ))}
        </ol>
      )}

      {!disabled && !isFormOpen && (
        <div className="flex flex-wrap gap-2">
          {pending ? null : budgets.length === 0 ? (
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
              {pending ? "Salvar e reenviar" : "Enviar ao cliente"}
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
