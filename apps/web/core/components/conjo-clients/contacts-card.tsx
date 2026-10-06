/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClient, TClientContact } from "@plane/types";
import { AlertModalCore, Checkbox, Input } from "@plane/ui";
// local imports
import { Card, Field, FormModal } from "./common";
import { conjoBillingService, getErrorMessage, initialOf } from "./helpers";

type Props = {
  workspaceSlug: string;
  client: TClient;
  isAdmin: boolean;
  onChanged: () => Promise<unknown>;
};

export function ContactsCard({ workspaceSlug, client, isAdmin, onChanged }: Props) {
  // undefined: closed; null: new contact; otherwise the contact being edited
  const [editing, setEditing] = useState<TClientContact | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<TClientContact | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDelete = async () => {
    if (!deleting) return;
    setIsDeleting(true);
    try {
      await conjoBillingService.deleteContact(workspaceSlug, client.id, deleting.id);
      await onChanged();
      setDeleting(null);
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível remover o contato."),
      });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Card
      title="Contatos"
      action={
        isAdmin && (
          <button
            type="button"
            className="text-13 font-medium text-accent-primary hover:underline"
            onClick={() => setEditing(null)}
          >
            Adicionar
          </button>
        )
      }
    >
      {client.contacts.length === 0 ? (
        <p className="text-12 text-tertiary">
          Nenhum contato cadastrado. Cadastre quem fala pelo cliente e marque quem pode aprovar orçamentos.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {client.contacts.map((contact) => (
            <li key={contact.id} className="group flex items-center gap-2.5">
              <span
                className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-layer-3 text-13 font-semibold text-primary"
                aria-hidden
              >
                {initialOf(contact.name)}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <b className="truncate text-13 font-semibold text-primary">{contact.name}</b>
                <span className="truncate text-12 text-tertiary">
                  {[contact.role, contact.email, contact.phone].filter(Boolean).join(" · ") || "Sem dados de contato"}
                </span>
              </span>
              {contact.can_approve && (
                <span className="rounded-full bg-success-subtle px-2 py-0.5 text-11 font-semibold text-success-primary">
                  aprova
                </span>
              )}
              {isAdmin && (
                <span className="flex items-center gap-0.5">
                  <button
                    type="button"
                    className="rounded-sm p-1 text-tertiary hover:bg-layer-1-hover hover:text-primary"
                    onClick={() => setEditing(contact)}
                    aria-label={`Editar ${contact.name}`}
                    title="Editar"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    className="rounded-sm p-1 text-tertiary hover:bg-layer-1-hover hover:text-danger-primary"
                    onClick={() => setDeleting(contact)}
                    aria-label={`Remover ${contact.name}`}
                    title="Remover"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <ContactModal
        isOpen={editing !== undefined}
        contact={editing ?? undefined}
        workspaceSlug={workspaceSlug}
        clientId={client.id}
        onClose={() => setEditing(undefined)}
        onSaved={onChanged}
      />
      <AlertModalCore
        isOpen={!!deleting}
        handleClose={() => setDeleting(null)}
        handleSubmit={() => void handleDelete()}
        isSubmitting={isDeleting}
        title="Remover contato"
        content={
          <>
            Remover <b className="font-medium text-primary">{deleting?.name}</b> dos contatos do cliente? Os registros
            antigos na linha do tempo continuam.
          </>
        }
        primaryButtonText={{ loading: "Removendo", default: "Remover" }}
        secondaryButtonText="Cancelar"
      />
    </Card>
  );
}

type TContactForm = { name: string; role: string; email: string; phone: string; can_approve: boolean };

const emptyContact: TContactForm = { name: "", role: "", email: "", phone: "", can_approve: false };

function ContactModal(props: {
  isOpen: boolean;
  contact?: TClientContact;
  workspaceSlug: string;
  clientId: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const { isOpen, contact, workspaceSlug, clientId, onClose, onSaved } = props;
  const [form, setForm] = useState<TContactForm>(emptyContact);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setForm(
      contact
        ? {
            name: contact.name,
            role: contact.role,
            email: contact.email,
            phone: contact.phone,
            can_approve: contact.can_approve,
          }
        : emptyContact
    );
  }, [isOpen, contact]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const payload = { ...form, name: form.name.trim(), email: form.email.trim() };
      if (contact) await conjoBillingService.updateContact(workspaceSlug, clientId, contact.id, payload);
      else await conjoBillingService.addContact(workspaceSlug, clientId, payload);
      await onSaved();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível salvar o contato."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title={contact ? "Editar contato" : "Novo contato"}
      submitLabel={contact ? "Salvar" : "Adicionar contato"}
      isSubmitting={isSubmitting}
      submitDisabled={!form.name.trim()}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nome" htmlFor="contact-name">
          <Input
            id="contact-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full"
            required
          />
        </Field>
        <Field label="Cargo ou área" htmlFor="contact-role">
          <Input
            id="contact-role"
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
            placeholder="Diretora, TI…"
            className="w-full"
          />
        </Field>
        <Field label="E-mail" htmlFor="contact-email">
          <Input
            id="contact-email"
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full"
          />
        </Field>
        <Field label="Telefone" htmlFor="contact-phone">
          <Input
            id="contact-phone"
            type="tel"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="w-full"
          />
        </Field>
      </div>
      <label htmlFor="contact-can-approve" className="flex items-start gap-2 text-13 text-primary">
        <Checkbox
          id="contact-can-approve"
          checked={form.can_approve}
          onChange={(e) => setForm({ ...form, can_approve: e.target.checked })}
          containerClassName="mt-0.5"
        />
        <span className="flex flex-col">
          Pode aprovar orçamentos
          <span className="text-12 text-tertiary">
            A aprovação de um orçamento debita as horas estimadas do pacote. O e-mail é usado para identificar quem
            aprova.
          </span>
        </span>
      </label>
    </FormModal>
  );
}
