/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import { Receipt } from "lucide-react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { mutate as globalMutate } from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import type { TClientLedger, THourLedgerEntry, TPackageSummary } from "@plane/types";
import { Input, Loader } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { Card, Chip, EmptyState, PageTitle, useIsClientsAdmin } from "./common";
import {
  LEDGER_KIND_CLASS,
  LEDGER_KIND_LABEL,
  clientKey,
  clientsKey,
  conjoBillingService,
  formatDayMonth,
  formatHours,
  formatLotPeriod,
  formatMinutes,
  formatMonthName,
  formatSignedHours,
  getErrorMessage,
  issueHref,
  lotBarClass,
  percentOf,
  toHours,
  toISODate,
} from "./helpers";
import { AdjustLedgerModal, ExportLedgerModal, ReverseDebitModal } from "./ledger-modals";

type Props = { workspaceSlug: string; clientId: string };

const defaultPeriod = () => {
  const today = new Date();
  const from = new Date(today.getFullYear(), today.getMonth() - 6, today.getDate());
  return { from: toISODate(from), to: toISODate(today) };
};

export const ClientLedger = observer(function ClientLedger({ workspaceSlug, clientId }: Props) {
  const isAdmin = useIsClientsAdmin(workspaceSlug);
  const [period, setPeriod] = useState(defaultPeriod);
  const [isAdjustOpen, setIsAdjustOpen] = useState(false);
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [reversing, setReversing] = useState<THourLedgerEntry | null>(null);

  const { data: client } = useSWR(workspaceSlug && clientId ? clientKey(workspaceSlug, clientId) : null, () =>
    conjoBillingService.getClient(workspaceSlug, clientId)
  );
  const {
    data: ledger,
    error,
    mutate,
  } = useSWR(
    workspaceSlug && clientId ? `CONJO_CLIENT_LEDGER_${workspaceSlug}_${clientId}_${period.from}_${period.to}` : null,
    () => conjoBillingService.getLedger(workspaceSlug, clientId, period),
    { keepPreviousData: true }
  );

  /** After a write: the statement, the client (balance) and the list. */
  const refresh = async () => {
    await mutate();
    void globalMutate(clientKey(workspaceSlug, clientId));
    void globalMutate(clientsKey(workspaceSlug));
  };

  const base = `/${workspaceSlug}/clients/${clientId}`;
  const pkg = ledger?.package ?? null;
  const contract = ledger?.contract;
  const month = formatMonthName(new Date());

  return (
    <div className="mx-auto flex w-full max-w-[1232px] flex-col gap-5 px-4 py-6 md:px-6">
      <PageTitle
        trail={[
          { label: "Clientes", href: `/${workspaceSlug}/clients` },
          { label: client?.name ?? "Cliente", href: base },
          { label: "Extrato" },
        ]}
        title="Extrato de horas"
        subtitle={
          contract
            ? `${contract.name} · cada crédito vale ${contract.accumulation_months} ${
                contract.accumulation_months === 1 ? "mês" : "meses"
              } · consome o crédito que vence primeiro`
            : undefined
        }
        actions={
          <>
            <div className="flex items-end gap-2">
              <label htmlFor="ledger-from" className="flex flex-col gap-0.5 text-11 text-tertiary">
                De
                <Input
                  id="ledger-from"
                  type="date"
                  value={period.from}
                  max={period.to}
                  onChange={(e) => e.target.value && setPeriod({ ...period, from: e.target.value })}
                  inputSize="xs"
                  className="h-8"
                />
              </label>
              <label htmlFor="ledger-to" className="flex flex-col gap-0.5 text-11 text-tertiary">
                Até
                <Input
                  id="ledger-to"
                  type="date"
                  value={period.to}
                  min={period.from}
                  onChange={(e) => e.target.value && setPeriod({ ...period, to: e.target.value })}
                  inputSize="xs"
                  className="h-8"
                />
              </label>
            </div>
            {isAdmin && pkg && (
              <>
                <Button variant="secondary" size="xl" onClick={() => setIsExportOpen(true)}>
                  Exportar para o financeiro
                </Button>
                <Button variant="primary" size="xl" onClick={() => setIsAdjustOpen(true)}>
                  Ajuste manual
                </Button>
              </>
            )}
          </>
        }
      />

      {error && !ledger ? (
        <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
          {getErrorMessage(error, "Não foi possível carregar o extrato. Recarregue a página.")}
        </div>
      ) : !ledger ? (
        <Loader className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Loader.Item height="76px" width="100%" />
            <Loader.Item height="76px" width="100%" />
            <Loader.Item height="76px" width="100%" />
            <Loader.Item height="76px" width="100%" />
          </div>
          <Loader.Item height="320px" width="100%" />
        </Loader>
      ) : !pkg ? (
        <EmptyState
          icon={<Receipt className="size-8" />}
          title="O cliente não tem contrato ativo"
          description="O extrato mostra os créditos mensais, débitos, expirações e ajustes de um contrato de pacote de horas."
          action={
            isAdmin && (
              <Link
                href={`${base}/contract`}
                className="rounded-md bg-accent-primary px-3 py-1.5 text-13 font-medium text-on-color hover:bg-accent-primary-hover"
              >
                Criar contrato
              </Link>
            )
          }
        />
      ) : (
        <>
          <SummaryCards pkg={pkg} month={month} maintenanceMinutes={client?.maintenance_minutes_this_month ?? null} />
          <div className="flex flex-wrap items-start gap-5">
            <section className="w-full min-w-0 flex-[999_1_640px] overflow-hidden rounded-lg border border-subtle bg-layer-1">
              <LedgerTable
                ledger={ledger}
                workspaceSlug={workspaceSlug}
                canReverse={isAdmin}
                onReverse={setReversing}
              />
            </section>
            <ActiveCredits pkg={pkg} />
          </div>
        </>
      )}

      <AdjustLedgerModal
        isOpen={isAdjustOpen}
        workspaceSlug={workspaceSlug}
        clientId={clientId}
        onClose={() => setIsAdjustOpen(false)}
        onSaved={refresh}
      />
      <ReverseDebitModal
        isOpen={!!reversing}
        entry={reversing}
        workspaceSlug={workspaceSlug}
        clientId={clientId}
        onClose={() => setReversing(null)}
        onSaved={refresh}
      />
      <ExportLedgerModal
        isOpen={isExportOpen}
        workspaceSlug={workspaceSlug}
        clientId={clientId}
        from={period.from}
        to={period.to}
        onClose={() => setIsExportOpen(false)}
        // the download marks the excess on the server; reload once it had time to run
        onExported={() => window.setTimeout(() => void mutate(), 2000)}
      />
    </div>
  );
});

function SummaryCard({ label, value, extra }: { label: string; value: string; extra?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-subtle bg-layer-1 p-4">
      <span className="text-12 text-tertiary">{label}</span>
      <span className="text-24 leading-8 font-semibold text-primary">
        {value} {extra && <span className="font-normal text-13 text-tertiary">{extra}</span>}
      </span>
    </div>
  );
}

function SummaryCards(props: { pkg: TPackageSummary; month: string; maintenanceMinutes: number | null }) {
  const { pkg, month, maintenanceMinutes } = props;
  const first = pkg.lots[0];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <SummaryCard label="Disponível" value={formatHours(pkg.available)} extra={`de ${formatHours(pkg.max_balance)}`} />
      <SummaryCard
        label="Vence primeiro"
        value={first ? formatHours(first.remaining) : "—"}
        extra={first?.expires_on ? `em ${formatDayMonth(first.expires_on)}` : undefined}
      />
      <SummaryCard label={`Debitado em ${month}`} value={formatHours(pkg.debited_this_month)} />
      <SummaryCard
        label={`Manutenção em ${month}`}
        value={maintenanceMinutes === null ? "—" : formatMinutes(maintenanceMinutes)}
        extra="não desconta"
      />
    </div>
  );
}

/** "Origem" column: the issue for debits, the month for credits, the note otherwise. */
function Origin({ entry, workspaceSlug }: { entry: THourLedgerEntry; workspaceSlug: string }) {
  const issue = entry.issue && (
    <>
      <Link href={issueHref(workspaceSlug, entry.issue)} className="font-medium text-accent-primary hover:underline">
        {entry.issue.key}
      </Link>{" "}
      {entry.issue.name}
    </>
  );
  const note = entry.note ? <span className="text-tertiary">{entry.note}</span> : null;
  const parts: ReactNode[] = [];
  switch (entry.kind) {
    case "credit":
      parts.push(
        `Crédito mensal de ${formatMonthName(entry.period)}${
          entry.expires_on ? ` · vale até ${formatDayMonth(entry.expires_on)}` : ""
        }`
      );
      break;
    case "expiration":
      parts.push(
        `Sobra do crédito de ${entry.lot_periods.map(formatMonthName).join(", ") || "meses anteriores"}, não usada`
      );
      break;
    case "excess":
      parts.push(issue, `${formatHours(entry.hours)} além do saldo`);
      break;
    case "adjustment":
      parts.push(entry.author ? `Ajuste manual por ${entry.author.display_name}` : "Ajuste manual");
      break;
    default:
      parts.push(issue);
  }
  parts.push(note);
  const visible = parts.filter(Boolean);
  return (
    <>
      {visible.map((part, index) => (
        // oxlint-disable-next-line react/no-array-index-key
        <span key={index}>
          {index > 0 && " · "}
          {part}
        </span>
      ))}
      {entry.reversed && <Chip className="ml-1.5 bg-layer-3 text-tertiary">estornado</Chip>}
    </>
  );
}

const creditUsed = (entry: THourLedgerEntry) => {
  const periods = entry.lot_periods.map(formatLotPeriod).join(", ");
  switch (entry.kind) {
    case "debit":
    case "expiration":
      return periods || "—";
    case "reversal":
      return periods ? `volta para ${periods}` : "—";
    case "excess":
      return entry.exported_at ? "exportado ao financeiro" : "a exportar";
    default:
      return "—";
  }
};

const hoursClass = (entry: THourLedgerEntry) => {
  if (entry.kind === "excess") return "text-danger-primary";
  if (entry.kind === "expiration") return "text-warning-primary";
  return toHours(entry.hours) > 0 ? "text-success-primary" : "text-primary";
};

function LedgerTable(props: {
  ledger: TClientLedger;
  workspaceSlug: string;
  canReverse: boolean;
  onReverse: (entry: THourLedgerEntry) => void;
}) {
  const { ledger, workspaceSlug, canReverse, onReverse } = props;
  if (ledger.entries.length === 0)
    return <p className="px-4 py-10 text-center text-13 text-tertiary">Nenhum movimento no período.</p>;

  const th = "px-2 py-2.5 text-left text-12 font-semibold text-tertiary first:pl-4 last:pr-4";
  const td = "border-t border-subtle px-2 py-3 align-top first:pl-4 last:pr-4";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-13">
        <caption className="sr-only">Movimentos do pacote de horas no período</caption>
        <thead>
          <tr>
            <th scope="col" className={th}>
              Data
            </th>
            <th scope="col" className={th}>
              Movimento
            </th>
            <th scope="col" className={th}>
              Origem
            </th>
            <th scope="col" className={th}>
              Crédito usado
            </th>
            <th scope="col" className={cn(th, "text-right")}>
              Horas
            </th>
            <th scope="col" className={cn(th, "text-right")}>
              Saldo
            </th>
            {canReverse && (
              <th scope="col" className={th}>
                <span className="sr-only">Ações</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {ledger.entries.map((entry) => (
            <tr key={entry.id} className={cn({ "opacity-60": entry.reversed })}>
              <td className={cn(td, "whitespace-nowrap text-secondary")}>{formatDayMonth(entry.occurred_on)}</td>
              <td className={td}>
                <Chip className={LEDGER_KIND_CLASS[entry.kind]}>{LEDGER_KIND_LABEL[entry.kind]}</Chip>
              </td>
              <td className={cn(td, "text-primary")}>
                <Origin entry={entry} workspaceSlug={workspaceSlug} />
              </td>
              <td className={cn(td, "whitespace-nowrap text-secondary")}>{creditUsed(entry)}</td>
              <td className={cn(td, "font-mono text-right whitespace-nowrap", hoursClass(entry))}>
                {entry.kind === "excess" ? formatHours(entry.hours) : formatSignedHours(entry.hours)}
              </td>
              <td className={cn(td, "font-mono text-right whitespace-nowrap text-primary")}>
                {formatHours(entry.balance)}
              </td>
              {canReverse && (
                <td className={cn(td, "text-right")}>
                  {entry.kind === "debit" && !entry.reversed && (
                    <button
                      type="button"
                      className="rounded-sm px-1.5 py-0.5 text-12 font-medium text-accent-primary hover:bg-layer-1-hover"
                      onClick={() => onReverse(entry)}
                      aria-label={`Estornar débito de ${formatHours(entry.hours)}${
                        entry.issue ? ` de ${entry.issue.key}` : ""
                      }`}
                    >
                      Estornar
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActiveCredits({ pkg }: { pkg: TPackageSummary }) {
  return (
    <Card title="Créditos ativos" className="w-full flex-[1_1_280px] lg:max-w-[320px]">
      {pkg.lots.length === 0 && <p className="text-12 text-tertiary">Nenhum crédito válido no momento.</p>}
      {pkg.lots.map((lot, index) => (
        <div key={lot.id} className="flex flex-col gap-1.5">
          <span className="flex items-baseline justify-between gap-2 text-13">
            <b className="font-semibold text-primary capitalize">
              {lot.kind === "adjustment" ? "Ajuste" : formatMonthName(lot.period) || "Crédito"}
            </b>
            <span className="text-secondary">
              {formatHours(lot.remaining)} de {formatHours(lot.hours)}
            </span>
          </span>
          <span className="block h-1.5 overflow-hidden rounded-full bg-layer-3" aria-hidden>
            <span
              className={cn("block h-full rounded-full", lotBarClass(index))}
              style={{ width: `${percentOf(lot.remaining, lot.hours)}%` }}
            />
          </span>
          <span className="text-12 text-tertiary">
            {lot.expires_on ? `vence em ${formatDayMonth(lot.expires_on)}` : "sem validade"}
            {index === 0 && pkg.lots.length > 1 ? " · usado primeiro" : ""}
          </span>
        </div>
      ))}
      <p className="border-t border-subtle pt-3 text-12 text-tertiary">
        Ajustes manuais exigem justificativa e ficam registrados com o autor. Manutenção e Interno não aparecem como
        débito, só nos relatórios.
      </p>
    </Card>
  );
}
