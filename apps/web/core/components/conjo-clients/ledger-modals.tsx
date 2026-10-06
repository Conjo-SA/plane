/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { THourLedgerEntry } from "@plane/types";
import { Checkbox, Input, TextArea } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { Field, FormModal } from "./common";
import { conjoBillingService, formatFullDate, formatHours, getErrorMessage } from "./helpers";

type TBaseProps = {
  isOpen: boolean;
  workspaceSlug: string;
  clientId: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
};

/** Manual adjustment: hours in or out of the balance, always with a note. */
export function AdjustLedgerModal({ isOpen, workspaceSlug, clientId, onClose, onSaved }: TBaseProps) {
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setDirection("in");
    setHours("");
    setNote("");
  }, [isOpen]);

  const amount = Number.parseFloat(hours.replace(",", "."));
  const isValid = Number.isFinite(amount) && amount > 0 && !!note.trim();

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const signed = (direction === "in" ? amount : -amount).toFixed(2);
      await conjoBillingService.adjustLedger(workspaceSlug, clientId, signed, note.trim());
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Ajuste registrado", message: "O saldo foi atualizado." });
      await onSaved();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível registrar o ajuste."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title="Ajuste manual"
      description="Use para corrigir o saldo. O ajuste fica no extrato com a justificativa e o autor."
      submitLabel="Registrar ajuste"
      isSubmitting={isSubmitting}
      submitDisabled={!isValid}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-12 font-medium text-secondary">Tipo</legend>
        <div className="flex flex-wrap gap-1.5" role="radiogroup">
          {(
            [
              { key: "in", label: "Adicionar horas (+)" },
              { key: "out", label: "Remover horas (−)" },
            ] as const
          ).map((option) => (
            <button
              key={option.key}
              type="button"
              role="radio"
              aria-checked={direction === option.key}
              onClick={() => setDirection(option.key)}
              className={cn("rounded-full border px-3 py-1 text-13", {
                "border-transparent bg-accent-primary text-on-color": direction === option.key,
                "border-subtle text-secondary hover:bg-layer-1-hover": direction !== option.key,
              })}
            >
              {option.label}
            </button>
          ))}
        </div>
      </fieldset>
      <Field label="Horas" htmlFor="adjust-hours" helper="Em horas decimais: 1,5 = 1h30." className="sm:max-w-40">
        <Input
          id="adjust-hours"
          type="number"
          inputMode="decimal"
          min="0.25"
          step="0.25"
          value={hours}
          onChange={(e) => setHours(e.target.value)}
          className="w-full"
          required
        />
      </Field>
      <Field label="Justificativa (obrigatória)" htmlFor="adjust-note">
        <TextArea
          id="adjust-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="min-h-20 text-13"
          placeholder="Por que o saldo está sendo ajustado"
          required
        />
      </Field>
    </FormModal>
  );
}

/** Reverses an approved debit: the hours go back to the lots they came from. */
export function ReverseDebitModal(props: TBaseProps & { entry: THourLedgerEntry | null }) {
  const { isOpen, workspaceSlug, clientId, entry, onClose, onSaved } = props;
  const [note, setNote] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen) setNote("");
  }, [isOpen]);

  const handleSubmit = async () => {
    if (!entry) return;
    setIsSubmitting(true);
    try {
      await conjoBillingService.reverseDebit(workspaceSlug, clientId, entry.id, note.trim());
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Débito estornado", message: "As horas voltaram para o saldo." });
      await onSaved();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível estornar o débito."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title="Estornar débito"
      description={
        entry && (
          <>
            {formatHours(entry.hours)} de {formatFullDate(entry.occurred_on)}
            {entry.issue ? ` (${entry.issue.key} ${entry.issue.name})` : ""} voltam para os créditos de onde saíram.
          </>
        )
      }
      submitLabel="Estornar"
      isSubmitting={isSubmitting}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Field label="Observação (opcional)" htmlFor="reverse-note">
        <TextArea
          id="reverse-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="min-h-20 text-13"
          placeholder="Ex.: tarefa cancelada após a aprovação"
        />
      </Field>
    </FormModal>
  );
}

/** CSV for the finance system (debits, reversals and excess hours of the period). */
export function ExportLedgerModal(
  props: Omit<TBaseProps, "onSaved"> & {
    from: string;
    to: string;
    onExported: () => void;
  }
) {
  const { isOpen, workspaceSlug, clientId, from, to, onClose, onExported } = props;
  const [markExported, setMarkExported] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen) setMarkExported(true);
  }, [isOpen]);

  const handleSubmit = async () => {
    const url = conjoBillingService.ledgerExportUrl(workspaceSlug, clientId, { from, to });
    // The export is a plain authenticated GET: let the browser download it.
    const link = document.createElement("a");
    link.href = url;
    link.rel = "noopener";
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
    if (!markExported) {
      onClose();
      return;
    }
    setIsSubmitting(true);
    try {
      await conjoBillingService.markLedgerExported(workspaceSlug, clientId, { from, to });
      onExported();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "CSV baixado, mas o excedente não foi marcado",
        message: getErrorMessage(err, "Tente marcar de novo antes de enviar ao financeiro."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title="Exportar para o financeiro"
      description={`Baixa um CSV com os débitos, estornos e excedentes de ${formatFullDate(from)} a ${formatFullDate(to)}.`}
      submitLabel="Baixar CSV"
      isSubmitting={isSubmitting}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <label htmlFor="export-mark" className="flex items-start gap-2 text-13 text-primary">
        <Checkbox
          id="export-mark"
          checked={markExported}
          onChange={(e) => setMarkExported(e.target.checked)}
          containerClassName="mt-0.5"
        />
        <span className="flex flex-col">
          Marcar o excedente como exportado
          <span className="text-12 text-tertiary">
            Evita cobrar o mesmo excedente duas vezes: no extrato, ele passa a aparecer como exportado ao financeiro.
          </span>
        </span>
      </label>
    </FormModal>
  );
}
