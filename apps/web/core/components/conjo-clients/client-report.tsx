/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { Input, Loader } from "@plane/ui";
// components
import { PageHead } from "@/components/core/page-title";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import { ClientReportDocument, FONTS_HREF, PRINT_CSS, hoursText, periodText } from "./client-report-document";
import { Field, FormModal } from "./common";
import { conjoBillingService, endOfMonth, getErrorMessage, parseDateOnly, toISODate } from "./helpers";

/* ------------------------------------------------------------------ */
/* Period                                                              */
/* ------------------------------------------------------------------ */

/** Previous calendar month, the default period of the report. */
export const previousMonthPeriod = (today = new Date()) => {
  const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  return { from: toISODate(start), to: toISODate(endOfMonth(start)) };
};

const isISODate = (value: string | null | undefined): value is string =>
  !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && parseDateOnly(value) !== null;

export const reportHref = (workspaceSlug: string, clientId: string, period: TPeriod) =>
  `/${workspaceSlug}/clients/${clientId}/report?${new URLSearchParams(period).toString()}`;

type TPeriod = { from: string; to: string };

/** Period picker of the report: "Emitir relatório" on the client page and "Mudar período" on the report. */
export function ReportPeriodModal(props: {
  isOpen: boolean;
  title: string;
  submitLabel: string;
  initial?: TPeriod;
  onClose: () => void;
  onSubmit: (period: TPeriod) => void;
}) {
  const { isOpen, title, submitLabel, initial, onClose, onSubmit } = props;
  const [period, setPeriod] = useState<TPeriod>(() => initial ?? previousMonthPeriod());

  useEffect(() => {
    if (isOpen) setPeriod(initial ?? previousMonthPeriod());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the modal opens
  }, [isOpen]);

  const invalid = !isISODate(period.from) || !isISODate(period.to) || period.to < period.from;

  return (
    <FormModal
      isOpen={isOpen}
      title={title}
      description="Relatório de atividades para enviar ao cliente: o que foi feito e onde as horas foram gastas."
      submitLabel={submitLabel}
      isSubmitting={false}
      submitDisabled={invalid}
      onClose={onClose}
      onSubmit={() => {
        onClose();
        onSubmit(period);
      }}
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="De" htmlFor="report-from">
          <Input
            id="report-from"
            type="date"
            value={period.from}
            onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))}
            className="w-full"
          />
        </Field>
        <Field label="Até" htmlFor="report-to" error={invalid ? "Informe um período válido." : undefined}>
          <Input
            id="report-to"
            type="date"
            value={period.to}
            min={period.from || undefined}
            onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))}
            className="w-full"
          />
        </Field>
      </div>
      <p className="text-12 text-tertiary">
        Entram os lançamentos de horas de itens de evolução e de manutenção do cliente. Itens internos ficam de fora.
      </p>
    </FormModal>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

/** Loads the fonts of the document only while the report is open. */
function useReportFonts() {
  useEffect(() => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = FONTS_HREF;
    document.head.appendChild(link);
    return () => link.remove();
  }, []);
}

type Props = { workspaceSlug: string; clientId: string };

export function ClientReport({ workspaceSlug, clientId }: Props) {
  const searchParams = useSearchParams();
  const router = useAppRouter();
  const fallback = previousMonthPeriod();
  const fromParam = searchParams.get("from");
  const toParam = searchParams.get("to");
  const period = {
    from: isISODate(fromParam) ? fromParam : fallback.from,
    to: isISODate(toParam) ? toParam : fallback.to,
  };
  const [isPeriodOpen, setIsPeriodOpen] = useState(false);
  useReportFonts();

  const { data: report, error } = useSWR(
    workspaceSlug && clientId ? `CONJO_CLIENT_REPORT_${workspaceSlug}_${clientId}_${period.from}_${period.to}` : null,
    () => conjoBillingService.getReport(workspaceSlug, clientId, period),
    { revalidateOnFocus: false }
  );

  // Body-level copy used only for printing, outside the app layout (which clips its content).
  const [printRoot, setPrintRoot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const element = document.createElement("div");
    element.className = "crp-print-root";
    document.body.appendChild(element);
    setPrintRoot(element);
    return () => element.remove();
  }, []);

  const base = `/${workspaceSlug}/clients/${clientId}`;

  return (
    <div className="flex w-full flex-col gap-4 px-4 py-6 md:px-6">
      <style>{PRINT_CSS}</style>
      {report && <PageHead title={`Relatório ${report.number} - ${report.client.legal_name || report.client.name}`} />}

      <div className="mx-auto flex w-full max-w-[900px] flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <Link href={base} className="text-13 text-tertiary hover:text-primary hover:underline">
            ← Voltar ao cliente
          </Link>
          <h1 className="text-18 font-semibold text-primary">Relatório de atividades</h1>
          <p className="text-13 text-secondary">{periodText(period.from, period.to)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="xl" onClick={() => setIsPeriodOpen(true)}>
            Mudar período
          </Button>
          <Button variant="primary" size="xl" disabled={!report} onClick={() => window.print()}>
            Salvar PDF / Imprimir
          </Button>
        </div>
      </div>

      {report && report.warnings.length > 0 && (
        <div className="mx-auto flex w-full max-w-[900px] flex-col gap-2" role="status">
          {report.warnings.map((warning) => (
            <div
              key={warning.type}
              className="rounded-lg border border-warning-subtle bg-warning-subtle px-4 py-3 text-13 text-primary"
            >
              <p className="font-medium">{warning.message}</p>
              {warning.items.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5 text-12 text-secondary">
                  {warning.items.map((item) => (
                    <li key={item.id}>
                      <Link
                        href={`/${workspaceSlug}/browse/${item.key}/`}
                        className="font-mono hover:text-primary hover:underline"
                      >
                        {item.key}
                      </Link>{" "}
                      {item.title} · {hoursText(item.hours)}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-1 text-11 text-tertiary">Este aviso aparece só para você e não sai no PDF.</p>
            </div>
          ))}
        </div>
      )}

      {error && !report && (
        <div className="mx-auto w-full max-w-[900px] rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
          {getErrorMessage(error, "Não foi possível gerar o relatório. Tente de novo.")}
        </div>
      )}

      {!report && !error && (
        <Loader className="mx-auto flex w-full max-w-[900px] flex-col gap-3">
          <Loader.Item height="600px" width="100%" />
        </Loader>
      )}

      {report && (
        <div className="overflow-x-auto rounded-lg bg-layer-2 py-6">
          <ClientReportDocument report={report} />
        </div>
      )}
      {report && printRoot && createPortal(<ClientReportDocument report={report} />, printRoot)}

      <ReportPeriodModal
        isOpen={isPeriodOpen}
        title="Mudar período"
        submitLabel="Atualizar relatório"
        initial={period}
        onClose={() => setIsPeriodOpen(false)}
        onSubmit={(next) => router.push(reportHref(workspaceSlug, clientId, next))}
      />
    </div>
  );
}
