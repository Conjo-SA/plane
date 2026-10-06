/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClientContact, TClientNoteKind } from "@plane/types";
import { Checkbox, Input, TextArea } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { Field, FormModal } from "./common";
import { conjoBillingService, getErrorMessage, toISODateTimeWithOffset, toLocalDateTimeInput } from "./helpers";

export const NOTE_KIND_LABEL: Record<TClientNoteKind, string> = {
  meeting: "Reunião",
  call: "Ligação",
  email: "E-mail",
  note: "Nota",
};

const NOTE_KINDS: TClientNoteKind[] = ["meeting", "call", "email", "note"];

type Props = {
  isOpen: boolean;
  workspaceSlug: string;
  clientId: string;
  contacts: TClientContact[];
  onClose: () => void;
  onSaved: () => Promise<unknown>;
};

export function NoteModal({ isOpen, workspaceSlug, clientId, contacts, onClose, onSaved }: Props) {
  const [kind, setKind] = useState<TClientNoteKind>("meeting");
  const [occurredAt, setOccurredAt] = useState("");
  const [contactIds, setContactIds] = useState<string[]>([]);
  const [body, setBody] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setKind("meeting");
    setOccurredAt(toLocalDateTimeInput(new Date()));
    setContactIds([]);
    setBody("");
  }, [isOpen]);

  const toggleContact = (contactId: string) =>
    setContactIds((current) =>
      current.includes(contactId) ? current.filter((id) => id !== contactId) : [...current, contactId]
    );

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const when = occurredAt ? new Date(occurredAt) : null;
      await conjoBillingService.addTimelineNote(workspaceSlug, clientId, {
        kind,
        body: body.trim(),
        occurred_at: when && !Number.isNaN(when.getTime()) ? toISODateTimeWithOffset(when) : undefined,
        contact_ids: contactIds,
      });
      await onSaved();
      onClose();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível registrar o contato."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      title="Registrar contato"
      description="Fica na linha do tempo do cliente, visível para a equipe."
      submitLabel="Registrar"
      isSubmitting={isSubmitting}
      submitDisabled={!body.trim()}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-12 font-medium text-secondary">Tipo</legend>
        <div className="flex flex-wrap gap-1.5" role="radiogroup">
          {NOTE_KINDS.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={kind === option}
              onClick={() => setKind(option)}
              className={cn("rounded-full border px-3 py-1 text-13", {
                "border-transparent bg-accent-primary text-on-color": kind === option,
                "border-subtle text-secondary hover:bg-layer-1-hover": kind !== option,
              })}
            >
              {NOTE_KIND_LABEL[option]}
            </button>
          ))}
        </div>
      </fieldset>

      <Field label="Quando" htmlFor="note-occurred-at" className="sm:max-w-60">
        <Input
          id="note-occurred-at"
          type="datetime-local"
          value={occurredAt}
          onChange={(e) => setOccurredAt(e.target.value)}
          className="w-full"
        />
      </Field>

      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-12 font-medium text-secondary">Com quem</legend>
        {contacts.length === 0 ? (
          <span className="text-12 text-tertiary">O cliente não tem contatos cadastrados.</span>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {contacts.map((contact) => (
              <label
                key={contact.id}
                htmlFor={`note-contact-${contact.id}`}
                className="flex items-center gap-2 text-13 text-primary"
              >
                <Checkbox
                  id={`note-contact-${contact.id}`}
                  checked={contactIds.includes(contact.id)}
                  onChange={() => toggleContact(contact.id)}
                />
                {contact.name}
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <Field label="O que foi conversado" htmlFor="note-body">
        <TextArea
          id="note-body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          className="min-h-28 text-13"
          placeholder="Assuntos, combinados e próximos passos"
          required
        />
      </Field>
    </FormModal>
  );
}
