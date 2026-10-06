/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { mutate as globalMutate } from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClient, TClientContract, TClientContractCreate } from "@plane/types";
import { Input, Loader, ToggleSwitch } from "@plane/ui";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import { Card, Field, PageTitle, useIsClientsAdmin } from "./common";
import {
  clientKey,
  clientsKey,
  conjoBillingService,
  endOfMonth,
  formatFullDate,
  formatHours,
  formatMonthName,
  getErrorMessage,
  toISODate,
} from "./helpers";

type Props = { workspaceSlug: string; clientId: string; contractId?: string };

type TForm = {
  name: string;
  hours_per_month: string;
  accumulation_months: string;
  credit_day: string;
  starts_on: string;
  ends_on: string;
  low_balance_percent: string;
  opening_balance: string;
  is_active: boolean;
};

const newForm = (): TForm => {
  const today = new Date();
  return {
    name: "",
    hours_per_month: "20",
    accumulation_months: "3",
    credit_day: "1",
    starts_on: toISODate(new Date(today.getFullYear(), today.getMonth(), 1)),
    ends_on: "",
    low_balance_percent: "20",
    opening_balance: "",
    is_active: true,
  };
};

const formFromContract = (contract: TClientContract): TForm => ({
  name: contract.name,
  hours_per_month: String(Number.parseFloat(contract.hours_per_month)),
  accumulation_months: String(contract.accumulation_months),
  credit_day: String(contract.credit_day),
  starts_on: contract.starts_on,
  ends_on: contract.ends_on ?? "",
  low_balance_percent: String(contract.low_balance_percent),
  opening_balance: "",
  is_active: contract.is_active,
});

const toNumber = (value: string) => Number.parseFloat(value.replace(",", "."));

/** Field errors in pt-BR; empty when the form can be saved. */
const validate = (form: TForm, isEdit: boolean): Partial<Record<keyof TForm, string>> => {
  const errors: Partial<Record<keyof TForm, string>> = {};
  const hours = toNumber(form.hours_per_month);
  const months = Number(form.accumulation_months);
  const day = Number(form.credit_day);
  const percent = Number(form.low_balance_percent);
  if (!form.name.trim()) errors.name = "Dê um nome ao contrato.";
  if (!Number.isFinite(hours) || hours <= 0) errors.hours_per_month = "Informe as horas por mês.";
  if (!Number.isInteger(months) || months < 1 || months > 12) errors.accumulation_months = "Entre 1 e 12 meses.";
  if (!Number.isInteger(day) || day < 1 || day > 28) errors.credit_day = "Entre 1 e 28.";
  if (!form.starts_on) errors.starts_on = "Informe o início.";
  if (form.ends_on && form.starts_on && form.ends_on < form.starts_on) errors.ends_on = "O fim vem depois do início.";
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) errors.low_balance_percent = "Entre 0 e 100%.";
  if (!isEdit && form.opening_balance) {
    const opening = toNumber(form.opening_balance);
    if (!Number.isFinite(opening) || opening < 0) errors.opening_balance = "Informe horas positivas.";
  }
  return errors;
};

export const ContractForm = observer(function ContractForm({ workspaceSlug, clientId, contractId }: Props) {
  const router = useAppRouter();
  const isAdmin = useIsClientsAdmin(workspaceSlug);
  const isEdit = !!contractId;
  const [form, setForm] = useState<TForm>(newForm);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: client, error } = useSWR(workspaceSlug && clientId ? clientKey(workspaceSlug, clientId) : null, () =>
    conjoBillingService.getClient(workspaceSlug, clientId)
  );
  const contract = contractId ? client?.contracts.find((item) => item.id === contractId) : undefined;

  // Fill the form once per contract (and the default name once per new contract).
  useEffect(() => {
    if (!client) return;
    const key = contractId ?? "new";
    if (loadedFor === key) return;
    if (contract) setForm(formFromContract(contract));
    else if (!contractId) setForm((current) => ({ ...current, name: current.name || "Pacote mensal 20h" }));
    setLoadedFor(key);
  }, [client, contract, contractId, loadedFor]);

  const errors = validate(form, isEdit);
  const hasErrors = Object.keys(errors).length > 0;
  const readOnly = !isAdmin;
  const base = `/${workspaceSlug}/clients/${clientId}`;

  const set = (key: keyof TForm) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (readOnly) return;
    if (hasErrors) {
      setShowErrors(true);
      return;
    }
    setIsSubmitting(true);
    const payload: TClientContractCreate = {
      name: form.name.trim(),
      hours_per_month: toNumber(form.hours_per_month).toFixed(2),
      accumulation_months: Number(form.accumulation_months),
      credit_day: Number(form.credit_day),
      starts_on: form.starts_on,
      ends_on: form.ends_on || null,
      low_balance_percent: Number(form.low_balance_percent),
      is_active: form.is_active,
    };
    try {
      if (contractId) await conjoBillingService.updateContract(workspaceSlug, clientId, contractId, payload);
      else
        await conjoBillingService.createContract(workspaceSlug, clientId, {
          ...payload,
          opening_balance: form.opening_balance ? toNumber(form.opening_balance).toFixed(2) : undefined,
        });
      await globalMutate(clientKey(workspaceSlug, clientId));
      void globalMutate(clientsKey(workspaceSlug));
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: isEdit ? "Contrato atualizado" : "Contrato criado",
        message: payload.name,
      });
      router.push(base);
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível salvar o contrato."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  if (error && !client)
    return (
      <div className="mx-auto w-full max-w-[1232px] px-4 py-6 md:px-6">
        <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
          {getErrorMessage(error, "Não foi possível carregar o cliente. Recarregue a página.")}
        </div>
      </div>
    );

  if (!client)
    return (
      <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
        <Loader className="space-y-2">
          <Loader.Item height="20px" width="200px" />
          <Loader.Item height="32px" width="320px" />
        </Loader>
        <Loader className="space-y-3">
          <Loader.Item height="320px" width="100%" />
        </Loader>
      </div>
    );

  if (contractId && !contract)
    return (
      <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-3 px-4 py-6 md:px-6">
        <p className="text-13 text-secondary">Contrato não encontrado.</p>
        <Link href={base} className="text-13 text-accent-primary hover:underline">
          Voltar para {client.name}
        </Link>
      </div>
    );

  const fieldError = (key: keyof TForm) => (showErrors ? errors[key] : undefined);

  return (
    <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
      <PageTitle
        trail={[
          { label: "Clientes", href: `/${workspaceSlug}/clients` },
          { label: client.name, href: base },
          { label: isEdit ? "Contrato" : "Novo contrato" },
        ]}
        title="Contrato de pacote de horas"
        subtitle={readOnly ? "Somente administradores do workspace alteram contratos." : undefined}
      />

      <div className="flex flex-wrap items-start gap-5">
        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="flex w-full min-w-0 flex-[999_1_560px] flex-col gap-5 rounded-lg border border-subtle bg-layer-1 p-5"
          noValidate
        >
          <fieldset disabled={readOnly || isSubmitting} className="flex flex-col gap-5">
            <Field label="Nome do contrato" htmlFor="contract-name" error={fieldError("name")}>
              <Input
                id="contract-name"
                value={form.name}
                onChange={set("name")}
                hasError={!!fieldError("name")}
                className="w-full"
              />
            </Field>

            <div className="flex flex-col gap-3">
              <h2 className="text-13 font-semibold text-secondary">Horas</h2>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Horas por mês" htmlFor="contract-hours" error={fieldError("hours_per_month")}>
                  <Input
                    id="contract-hours"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.5"
                    value={form.hours_per_month}
                    onChange={set("hours_per_month")}
                    hasError={!!fieldError("hours_per_month")}
                    className="w-full"
                  />
                </Field>
                <Field
                  label="Meses de acúmulo"
                  htmlFor="contract-months"
                  error={fieldError("accumulation_months")}
                  helper="Quanto tempo cada crédito mensal vale (1 = não acumula, 12 = o ano todo)."
                >
                  <Input
                    id="contract-months"
                    type="number"
                    min="1"
                    max="12"
                    step="1"
                    value={form.accumulation_months}
                    onChange={set("accumulation_months")}
                    hasError={!!fieldError("accumulation_months")}
                    className="w-full"
                  />
                </Field>
                <Field
                  label="Dia do crédito"
                  htmlFor="contract-day"
                  error={fieldError("credit_day")}
                  helper="Dia do mês em que as horas entram (1 a 28)."
                >
                  <Input
                    id="contract-day"
                    type="number"
                    min="1"
                    max="28"
                    step="1"
                    value={form.credit_day}
                    onChange={set("credit_day")}
                    hasError={!!fieldError("credit_day")}
                    className="w-full"
                  />
                </Field>
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Início" htmlFor="contract-start" error={fieldError("starts_on")}>
                  <Input
                    id="contract-start"
                    type="date"
                    value={form.starts_on}
                    onChange={set("starts_on")}
                    hasError={!!fieldError("starts_on")}
                    className="w-full"
                  />
                </Field>
                <Field
                  label="Fim (opcional)"
                  htmlFor="contract-end"
                  error={fieldError("ends_on")}
                  helper="Em branco: sem data de fim."
                >
                  <Input
                    id="contract-end"
                    type="date"
                    value={form.ends_on}
                    min={form.starts_on || undefined}
                    onChange={set("ends_on")}
                    hasError={!!fieldError("ends_on")}
                    className="w-full"
                  />
                </Field>
                <Field
                  label="Avisar com saldo abaixo de (%)"
                  htmlFor="contract-low"
                  error={fieldError("low_balance_percent")}
                  helper="Percentual do saldo máximo."
                >
                  <Input
                    id="contract-low"
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={form.low_balance_percent}
                    onChange={set("low_balance_percent")}
                    hasError={!!fieldError("low_balance_percent")}
                    className="w-full"
                  />
                </Field>
              </div>
            </div>

            {!isEdit && (
              <Field
                label="Saldo inicial (opcional)"
                htmlFor="contract-opening"
                error={fieldError("opening_balance")}
                helper="Horas que o cliente já tem ao cadastrar o contrato. Entram como um ajuste no extrato."
                className="sm:max-w-xs"
              >
                <Input
                  id="contract-opening"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="0.5"
                  value={form.opening_balance}
                  onChange={set("opening_balance")}
                  hasError={!!fieldError("opening_balance")}
                  placeholder="0"
                  className="w-full"
                />
              </Field>
            )}

            <div className="flex items-center justify-between gap-4 rounded-md border border-subtle px-3 py-2">
              <div className="flex flex-col">
                <span className="text-13 font-medium text-primary">Contrato ativo</span>
                <span className="text-12 text-tertiary">
                  O cliente tem um contrato ativo por vez: ativar este desativa o anterior.
                </span>
              </div>
              <ToggleSwitch
                value={form.is_active}
                onChange={() => setForm((current) => ({ ...current, is_active: !current.is_active }))}
                label="Contrato ativo"
                disabled={readOnly || isSubmitting}
                size="sm"
              />
            </div>
          </fieldset>

          <ApproversAndProjects client={client} base={base} />

          <div className="flex justify-end gap-2 border-t border-subtle pt-4">
            <Link
              href={base}
              className="inline-flex h-8 items-center rounded-md border border-strong bg-layer-2 px-3 text-body-sm-medium text-secondary hover:bg-layer-2-hover"
            >
              {readOnly ? "Voltar" : "Cancelar"}
            </Link>
            {!readOnly && (
              <Button type="submit" variant="primary" size="xl" loading={isSubmitting} disabled={isSubmitting}>
                Salvar contrato
              </Button>
            )}
          </div>
        </form>

        <HowItWorks form={form} />
      </div>
    </div>
  );
});

/** Approvers and projects are managed on the client page; here they are shown for context. */
function ApproversAndProjects({ client, base }: { client: TClient; base: string }) {
  const approvers = client.contacts.filter((contact) => contact.can_approve);
  return (
    <div className="grid gap-4 border-t border-subtle pt-4 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-13 font-semibold text-secondary">Quem pode aprovar orçamentos</h2>
        {approvers.length === 0 ? (
          <span className="text-12 text-tertiary">Nenhum contato marcado como aprovador.</span>
        ) : (
          <ul className="flex flex-col gap-1 text-13 text-primary">
            {approvers.map((contact) => (
              <li key={contact.id}>
                {contact.name}
                {contact.role && <span className="text-tertiary"> · {contact.role}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <h2 className="text-13 font-semibold text-secondary">Projetos cobertos</h2>
        {client.projects.length === 0 ? (
          <span className="text-12 text-tertiary">Nenhum projeto vinculado.</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {client.projects.map((project) => (
              <span key={project.id} className="rounded-sm bg-layer-2 px-2 py-0.5 text-12 text-primary">
                {project.identifier} · {project.name}
              </span>
            ))}
          </div>
        )}
      </div>
      <Link href={base} className="text-12 text-accent-primary hover:underline sm:col-span-2">
        Aprovadores e projetos são gerenciados na ficha do cliente
      </Link>
    </div>
  );
}

/** Live explanation of the contract, computed from the inputs. */
function HowItWorks({ form }: { form: TForm }) {
  const hours = toNumber(form.hours_per_month);
  const months = Number(form.accumulation_months);
  const day = Number(form.credit_day);
  const valid = Number.isFinite(hours) && hours > 0 && Number.isInteger(months) && months >= 1;

  const example = useMemo(() => {
    const today = new Date();
    return { month: formatMonthName(today), until: formatFullDate(toISODate(endOfMonth(today, months - 1))) };
  }, [months]);

  return (
    <aside className="flex w-full flex-[1_1_280px] flex-col gap-4 lg:max-w-[360px]">
      <Card title="Como esse contrato funciona">
        {valid ? (
          <>
            <p className="text-13 text-primary">
              Todo dia {Number.isInteger(day) && day >= 1 ? day : "—"} entram <b>{formatHours(hours)}</b>. Cada crédito
              vale <b>{months === 1 ? "1 mês" : `${months} meses`}</b>: o de {example.month} pode ser usado até{" "}
              {example.until}.
            </p>
            <p className="text-13 text-primary">
              Saldo máximo possível: <b>{formatHours(hours * months)}</b>.
            </p>
          </>
        ) : (
          <p className="text-13 text-tertiary">Preencha as horas por mês e os meses de acúmulo.</p>
        )}
        <p className="text-13 text-secondary">Os débitos usam primeiro o crédito mais antigo, o que vence antes.</p>
      </Card>
      <Card title="O que conta">
        <ul className="flex flex-col gap-2 text-13">
          <li className="flex justify-between gap-2">
            <span className="text-primary">Evolução (orçamento aprovado)</span>
            <b className="font-semibold text-primary">desconta</b>
          </li>
          <li className="flex justify-between gap-2">
            <span className="text-primary">Manutenção (bug)</span>
            <span className="text-tertiary">só registra</span>
          </li>
          <li className="flex justify-between gap-2">
            <span className="text-primary">Interno</span>
            <span className="text-tertiary">só registra</span>
          </li>
          <li className="flex justify-between gap-2">
            <span className="text-primary">Acima do saldo</span>
            <span className="text-danger-primary">vira excedente</span>
          </li>
        </ul>
      </Card>
    </aside>
  );
}
