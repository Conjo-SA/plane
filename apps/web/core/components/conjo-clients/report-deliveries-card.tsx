/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TClient, TClientReportDelivery, TClientReportDeliveryStatus } from "@plane/types";
import { Loader, ToggleSwitch } from "@plane/ui";
// local imports
import { periodText } from "./client-report-document";
import { ReportPeriodModal } from "./client-report";
import { Card } from "./common";
import { conjoBillingService, formatFullDate, formatTime, getErrorMessage } from "./helpers";

const STATUS: Record<TClientReportDeliveryStatus, { label: string; className: string }> = {
  pending: { label: "Na fila", className: "bg-layer-3 text-secondary" },
  sending: { label: "Enviando", className: "bg-layer-3 text-secondary" },
  sent: { label: "Enviado", className: "bg-success-subtle text-success-primary" },
  failed: { label: "Falhou", className: "bg-danger-subtle text-danger-primary" },
  skipped: { label: "Não enviado", className: "bg-warning-subtle text-warning-primary" },
};

const deliveriesKey = (workspaceSlug: string, clientId: string) =>
  `CONJO_CLIENT_REPORT_DELIVERIES_${workspaceSlug}_${clientId}`;

type Props = {
  workspaceSlug: string;
  client: TClient;
  isAdmin: boolean;
  onChanged: () => Promise<unknown>;
};

/** Monthly report by e-mail (CONJO-52): turn it on, who gets it, the last e-mails and a send by hand. */
export function ReportDeliveriesCard({ workspaceSlug, client, isAdmin, onChanged }: Props) {
  const [isSaving, setIsSaving] = useState(false);
  const [isSendOpen, setIsSendOpen] = useState(false);
  const { data, mutate } = useSWR(
    deliveriesKey(workspaceSlug, client.id),
    () => conjoBillingService.getReportDeliveries(workspaceSlug, client.id),
    // Refresh while an e-mail is still on its way.
    {
      refreshInterval: (latest) =>
        latest?.deliveries.some((d) => d.status === "pending" || d.status === "sending") ? 5000 : 0,
    }
  );
  const recipients = client.contacts.filter((contact) => contact.receives_report && contact.email);

  const toggle = async () => {
    setIsSaving(true);
    try {
      await conjoBillingService.updateClient(workspaceSlug, client.id, {
        monthly_report_enabled: !client.monthly_report_enabled,
      });
      await onChanged();
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível mudar o envio mensal."),
      });
    } finally {
      setIsSaving(false);
    }
  };

  const send = async (period: { from: string; to: string }) => {
    try {
      await conjoBillingService.sendReport(workspaceSlug, client.id, period);
      await mutate();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Relatório na fila",
        message: "O e-mail sai em instantes; acompanhe aqui no histórico.",
      });
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível enviar o relatório."),
      });
    }
  };

  return (
    <Card
      title="Relatório mensal por e-mail"
      action={
        isAdmin && (
          <button
            type="button"
            className="text-13 font-medium text-accent-primary hover:underline disabled:text-tertiary disabled:no-underline"
            disabled={recipients.length === 0}
            title={recipients.length === 0 ? "Marque um contato para receber o relatório" : undefined}
            onClick={() => setIsSendOpen(true)}
          >
            Enviar agora
          </button>
        )
      }
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-12 text-tertiary">
          No primeiro dia útil de cada mês, o relatório do mês anterior vai em PDF para os contatos marcados.
        </p>
        <ToggleSwitch
          value={client.monthly_report_enabled}
          onChange={() => void toggle()}
          disabled={!isAdmin || isSaving}
          size="sm"
          label="Enviar o relatório mensal por e-mail"
        />
      </div>

      <p className="text-12 text-secondary">
        {recipients.length > 0 ? (
          <>
            Recebem: <span className="text-primary">{recipients.map((c) => c.name).join(", ")}</span>
          </>
        ) : (
          <span className="text-warning-primary">
            Nenhum contato marcado para receber. Edite um contato e marque &quot;Recebe o relatório mensal&quot;.
          </span>
        )}
      </p>

      {data && !data.live && (
        <p className="rounded-md bg-warning-subtle px-3 py-2 text-12 text-primary">
          Ambiente de teste: os e-mails vão só para o endereço de teste, nunca para o cliente.
        </p>
      )}

      {!data ? (
        <Loader className="flex flex-col gap-2">
          <Loader.Item height="36px" width="100%" />
        </Loader>
      ) : data.deliveries.length === 0 ? (
        <p className="text-12 text-tertiary">Nenhum envio ainda.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.deliveries.slice(0, 6).map((delivery) => (
            <DeliveryRow key={delivery.id} delivery={delivery} />
          ))}
        </ul>
      )}

      <ReportPeriodModal
        isOpen={isSendOpen}
        title="Enviar relatório por e-mail"
        submitLabel="Enviar"
        onClose={() => setIsSendOpen(false)}
        onSubmit={(period) => void send(period)}
      />
    </Card>
  );
}

function DeliveryRow({ delivery }: { delivery: TClientReportDelivery }) {
  const status = STATUS[delivery.status];
  const when = delivery.sent_at ?? delivery.created_at;
  const to = delivery.delivered_to.length > 0 ? delivery.delivered_to : delivery.recipients;
  return (
    <li className="flex flex-col gap-0.5 rounded-md border border-subtle px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-13 font-medium text-primary">
          {periodText(delivery.period.from, delivery.period.to)}
        </span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-11 font-semibold ${status.className}`}>
          {status.label}
        </span>
      </div>
      <span className="text-11 text-tertiary">
        {delivery.trigger === "auto" ? "Mensal" : "Manual"}
        {delivery.created_by && ` por ${delivery.created_by.display_name}`} · {formatFullDate(when)} {formatTime(when)}
        {to.length > 0 && ` · ${delivery.test_mode ? "teste: " : ""}${to.join(", ")}`}
      </span>
      {delivery.reason && <span className="text-12 text-secondary">{delivery.reason}</span>}
    </li>
  );
}
