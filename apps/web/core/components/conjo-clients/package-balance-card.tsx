/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { AlertTriangle, Clock } from "lucide-react";
import Link from "next/link";
// plane imports
import type { THourLot, TPackageSummary } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { Card, EmptyState } from "./common";
import { formatDayMonth, formatHours, formatLotPeriod, formatMinutes, lotBarClass, percentOf } from "./helpers";

type Props = {
  pkg: TPackageSummary | null;
  maintenanceMinutes: number;
  /** Link to create the contract, shown to admins when there is no package. */
  newContractHref?: string;
};

export const lotLabel = (lot: THourLot) => {
  const expiry = lot.expires_on ? `Vence em ${formatDayMonth(lot.expires_on)}` : "Sem validade";
  return lot.kind === "adjustment" ? `Ajuste · ${expiry.toLowerCase()}` : expiry;
};

/** Bar of the package balance split by lot, the one that expires first first. */
export function LotsBar({ pkg, className }: { pkg: TPackageSummary; className?: string }) {
  return (
    <div
      className={cn("flex h-2 overflow-hidden rounded-full bg-layer-3", className)}
      role="img"
      aria-label={`${formatHours(pkg.available)} disponíveis de ${formatHours(pkg.max_balance)}`}
    >
      {pkg.lots.map((lot, index) => (
        <span
          key={lot.id}
          className={cn("h-full", lotBarClass(index))}
          style={{ width: `${percentOf(lot.remaining, pkg.max_balance)}%` }}
        />
      ))}
    </div>
  );
}

export function PackageBalanceCard({ pkg, maintenanceMinutes, newContractHref }: Props) {
  if (!pkg)
    return (
      <Card title="Saldo do pacote">
        <EmptyState
          icon={<Clock className="size-6" />}
          title="Sem contrato de pacote de horas"
          description="Com um contrato ativo, o cliente recebe as horas do mês e os orçamentos aprovados são debitados do saldo."
          action={
            newContractHref && (
              <Link
                href={newContractHref}
                className="rounded-md bg-accent-primary px-3 py-1.5 text-13 font-medium text-on-color hover:bg-accent-primary-hover"
              >
                Criar contrato
              </Link>
            )
          }
        />
      </Card>
    );

  return (
    <Card
      title="Saldo do pacote"
      action={
        <span className="text-12 text-tertiary">
          {formatHours(pkg.hours_per_month)}/mês · acumula {pkg.accumulation_months}{" "}
          {pkg.accumulation_months === 1 ? "mês" : "meses"}
        </span>
      }
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-32 leading-10 font-semibold text-primary">{formatHours(pkg.available)}</span>
        <span className="text-13 text-secondary">disponíveis de {formatHours(pkg.max_balance)} possíveis</span>
      </div>
      {pkg.low_balance && (
        <span className="flex items-center gap-1.5 rounded-md bg-warning-subtle px-2 py-1 text-12 font-medium text-warning-primary">
          <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
          Saldo baixo: avise o cliente antes de aprovar novos orçamentos.
        </span>
      )}
      <LotsBar pkg={pkg} />
      <ul className="flex flex-col gap-1.5 text-13">
        {pkg.lots.map((lot, index) => (
          <li key={lot.id} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-primary">
              <span className={cn("size-2 shrink-0 rounded-full", lotBarClass(index))} aria-hidden />
              {lotLabel(lot)}
              {lot.period && <span className="text-12 text-tertiary">({formatLotPeriod(lot.period)})</span>}
            </span>
            <b className="font-semibold text-primary">{formatHours(lot.remaining)}</b>
          </li>
        ))}
        {pkg.lots.length === 0 && <li className="text-12 text-tertiary">Nenhum crédito válido no momento.</li>}
        <li className="flex items-center justify-between gap-2 text-secondary">
          <span>Manutenção no mês (não desconta)</span>
          <span>{formatMinutes(maintenanceMinutes)}</span>
        </li>
      </ul>
    </Card>
  );
}
