/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClient } from "@plane/types";
import { Input, TextArea, ToggleSwitch } from "@plane/ui";
// local imports
import { Field, FormModal } from "./common";
import { conjoBillingService, getErrorMessage } from "./helpers";

type Props = {
  isOpen: boolean;
  workspaceSlug: string;
  /** When given, edits this client; otherwise creates a new one. */
  client?: TClient;
  onClose: () => void;
  onSaved: (client: TClient) => void | Promise<void>;
};

type TForm = { name: string; legal_name: string; document: string; notes: string; is_active: boolean };

const emptyForm: TForm = { name: "", legal_name: "", document: "", notes: "", is_active: true };

export function ClientFormModal(props: Props) {
  const { isOpen, workspaceSlug, client, onClose, onSaved } = props;
  const [form, setForm] = useState<TForm>(emptyForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isEdit = !!client;

  useEffect(() => {
    if (!isOpen) return;
    setForm(
      client
        ? {
            name: client.name,
            legal_name: client.legal_name,
            document: client.document,
            notes: client.notes,
            is_active: client.is_active,
          }
        : emptyForm
    );
  }, [isOpen, client]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const payload = {
        name: form.name.trim(),
        legal_name: form.legal_name.trim(),
        document: form.document.trim(),
        notes: form.notes,
      };
      const saved = client
        ? await conjoBillingService.updateClient(workspaceSlug, client.id, { ...payload, is_active: form.is_active })
        : await conjoBillingService.createClient(workspaceSlug, payload);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: isEdit ? "Cliente atualizado" : "Cliente criado",
        message: saved.name,
      });
      await onSaved(saved);
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível salvar o cliente."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title={isEdit ? "Editar cliente" : "Novo cliente"}
      submitLabel={isEdit ? "Salvar" : "Criar cliente"}
      isSubmitting={isSubmitting}
      submitDisabled={!form.name.trim()}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Field label="Nome" htmlFor="client-name">
        <Input
          id="client-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Como o cliente é chamado no dia a dia"
          className="w-full"
          required
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Razão social" htmlFor="client-legal-name">
          <Input
            id="client-legal-name"
            value={form.legal_name}
            onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
            className="w-full"
          />
        </Field>
        <Field label="CNPJ" htmlFor="client-document">
          <Input
            id="client-document"
            value={form.document}
            onChange={(e) => setForm({ ...form, document: e.target.value })}
            placeholder="00.000.000/0000-00"
            inputMode="numeric"
            className="w-full"
          />
        </Field>
      </div>
      {isEdit && (
        <>
          <Field label="Observações" htmlFor="client-notes">
            <TextArea
              id="client-notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="min-h-20 text-13"
            />
          </Field>
          <div className="flex items-center justify-between gap-4 rounded-md border border-subtle px-3 py-2">
            <div className="flex flex-col">
              <span className="text-13 font-medium text-primary">Cliente ativo</span>
              <span className="text-12 text-tertiary">
                Clientes inativos continuam no histórico, mas saem da lista.
              </span>
            </div>
            <ToggleSwitch
              value={form.is_active}
              onChange={() => setForm({ ...form, is_active: !form.is_active })}
              label="Cliente ativo"
              size="sm"
            />
          </div>
        </>
      )}
    </FormModal>
  );
}
