/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TIntakePortalPackage } from "@plane/types";
// helpers
import { formatDayMonth, formatHours, formatMinutes, hoursToMinutes } from "@/helpers/portal-hours";

/** "Horas disponíveis no seu pacote": balance of the requester's client, at the top of the ticket list. */
export function PortalPackageBalanceCard({ pkg }: { pkg: TIntakePortalPackage }) {
  const expiring = pkg.next_expiring;
  const showExpiring = !!expiring?.expires_on && hoursToMinutes(expiring.hours) > 0;
  const months = pkg.accumulation_months;
  return (
    <section className="flex flex-wrap items-center gap-x-8 gap-y-4 rounded-lg border border-subtle bg-layer-1 px-5 py-5">
      <div className="flex min-w-[220px] flex-1 flex-col gap-1">
        <span className="text-13 text-secondary">Horas disponíveis no seu pacote</span>
        <span className="text-[40px] leading-[44px] font-semibold text-primary">{formatHours(pkg.available)}</span>
        {showExpiring && expiring && (
          <span className="text-13 text-warning-primary">
            {formatHours(expiring.hours)} vencem em {formatDayMonth(expiring.expires_on)} se não forem usadas
          </span>
        )}
      </div>
      <div className="flex min-w-[220px] flex-1 flex-col gap-1 text-13 text-secondary">
        <span>
          Pacote: {formatHours(pkg.hours_per_month)} por mês
          {months > 0 && `, cada crédito vale ${months} ${months === 1 ? "mês" : "meses"}`}
        </span>
        <span>Correções de bug não descontam do pacote</span>
        {pkg.client_name && <span className="text-tertiary">{pkg.client_name}</span>}
      </div>
    </section>
  );
}

/** Balance after approving an estimate, or how many hours go beyond it and are billed separately. */
export function PortalBalanceAfterApproval({
  pkg,
  estimatedHours,
}: {
  pkg: TIntakePortalPackage;
  estimatedHours: number;
}) {
  const after = hoursToMinutes(pkg.available) - hoursToMinutes(estimatedHours);
  return (
    <div>
      <p className="text-12 text-tertiary">Seu saldo depois da aprovação</p>
      <p className="text-20 leading-tight font-semibold text-primary">{formatMinutes(Math.max(after, 0))}</p>
      {after < 0 && (
        <p className="mt-0.5 text-12 font-medium text-warning-primary">
          {formatMinutes(-after)} além do saldo serão cobradas à parte
        </p>
      )}
    </div>
  );
}
