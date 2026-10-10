/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { CSSProperties, ReactNode } from "react";
// plane imports
import type { TClientReport, TClientReportKind } from "@plane/types";
// local imports
import { endOfMonth, formatFullDate, formatMonthName, parseDateOnly, toHours, toISODate } from "./helpers";

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

const NUMBER = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

/** "30.50" → "30,5 h". */
export const hoursText = (value: string | number) => `${NUMBER.format(toHours(value))} h`;

const pad = (value: number) => String(value).padStart(2, "0");

const dayMonth = (value: string) => {
  const date = parseDateOnly(value);
  return date ? `${pad(date.getDate())}/${pad(date.getMonth() + 1)}` : value;
};

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** "Setembro de 2026 (01/09 a 30/09)" for a calendar month; "01/09/2026 a 15/09/2026" otherwise. */
export const periodText = (from: string, to: string) => {
  const start = parseDateOnly(from);
  const end = parseDateOnly(to);
  if (start && end && start.getDate() === 1 && toISODate(endOfMonth(start)) === to) {
    return `${capitalize(formatMonthName(start))} de ${start.getFullYear()} (${dayMonth(from)} a ${dayMonth(to)})`;
  }
  return from === to ? formatFullDate(from) : `${formatFullDate(from)} a ${formatFullDate(to)}`;
};

const pct = (part: number, total: number) =>
  total > 0 ? `${Math.max(0, Math.min(100, (part / total) * 100))}%` : "0%";

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/* ------------------------------------------------------------------ */
/* Visual tokens (from the approved design; the document is always light) */
/* ------------------------------------------------------------------ */

const INK = "#141414";
const MUTED = "#6B6B66";
const FAINT = "#8A8A84";
const SOFT_INK = "#3D3D3A";
const LINE = "#ECECE8";
const TRACK = "#F1F1EE";
const PANEL = "#F6F6F3";
const EVO = "#2B5BA8";
const MAN = "#18794E";
const MONO = "'JetBrains Mono', ui-monospace, monospace";

const KIND: Record<TClientReportKind, { label: string; bg: string; ink: string; color: string; kpi: string }> = {
  evolution: { label: "Evolução", bg: "#E7EEF9", ink: EVO, color: EVO, kpi: "#EEF3FB" },
  maintenance: { label: "Manutenção", bg: "#E6F4EC", ink: MAN, color: MAN, kpi: "#EDF7F1" },
};

export const FONTS_HREF =
  "https://fonts.googleapis.com/css2?family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700;6..12,800&family=JetBrains+Mono:wght@400;500;600&display=swap";

/** Print rules: only the report copy (portal under <body>) is printed, on A4 with page numbers. */
export const PRINT_CSS = `
.crp-print-root { display: none; }
.crp-doc { font-family: 'Nunito Sans', system-ui, sans-serif; color: ${INK}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.crp-doc h1, .crp-doc h2, .crp-doc p, .crp-doc dl, .crp-doc dd { margin: 0; }
.crp-sheet { width: 210mm; max-width: 100%; min-height: 297mm; box-sizing: border-box; background: #FFFFFF; display: flex; flex-direction: column; box-shadow: 0 1px 2px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.08); }
.crp-doc tr { break-inside: avoid; }
.crp-keep { break-inside: avoid; }
@page { size: A4; margin: 12mm 0 14mm; @bottom-right { content: "Página " counter(page) " de " counter(pages); font-family: 'Nunito Sans', system-ui, sans-serif; font-size: 8pt; color: ${FAINT}; margin-right: 14mm; } }
@media print {
  html, body { background: #FFFFFF !important; height: auto !important; min-height: 0 !important; overflow: visible !important; }
  body > *:not(.crp-print-root) { display: none !important; }
  .crp-print-root { display: block !important; }
  .crp-sheet { width: auto; min-height: 0; box-shadow: none; }
  .crp-sheet + .crp-sheet { break-before: page; }
  .crp-sheet header:first-child { padding-top: 0 !important; }
}
`;

/* ------------------------------------------------------------------ */
/* Document                                                            */
/* ------------------------------------------------------------------ */

function Tag({ kind, small }: { kind: TClientReportKind; small?: boolean }) {
  const style = KIND[kind];
  return (
    <span
      style={{
        height: small ? 18 : 20,
        padding: small ? "0 6px" : "0 7px",
        borderRadius: small ? 5 : 6,
        display: "inline-flex",
        alignItems: "center",
        fontSize: small ? 10 : 10.5,
        fontWeight: 700,
        background: style.bg,
        color: style.ink,
        whiteSpace: "nowrap",
      }}
    >
      {style.label}
    </span>
  );
}

const h2: CSSProperties = { fontSize: 14, fontWeight: 800 };
const section = (top = 22): CSSProperties => ({ padding: `${top}px 52px 0` });

function Legend({ color, border, children }: { color: string; border?: boolean; children: ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: 3,
          background: color,
          border: border ? "1px solid #DDDDD8" : undefined,
          boxSizing: "border-box",
        }}
      />
      {children}
    </span>
  );
}

function Footer({ children }: { children: ReactNode }) {
  return (
    <footer
      style={{
        marginTop: "auto",
        padding: "16px 52px 26px",
        display: "flex",
        justifyContent: "space-between",
        gap: 16,
        fontSize: 10.5,
        color: FAINT,
        borderTop: `1px solid ${LINE}`,
      }}
    >
      {children}
    </footer>
  );
}

export function ClientReportDocument({ report }: { report: TClientReport }) {
  const period = periodText(report.period.from, report.period.to);
  const issued = formatFullDate(report.issued_on);
  const clientName = report.client.legal_name || report.client.name;
  const { totals } = report;
  const open = totals.items - totals.done_items;
  const pkg = report.package;
  const contracted = pkg ? toHours(pkg.contracted) : 0;
  const pkgUsed = pkg ? toHours(pkg.used_before) + toHours(pkg.used_in_period) : 0;
  const validity =
    pkg?.valid_until &&
    (pkg.next_expiry && pkg.next_expiry !== pkg.valid_until
      ? `válido até ${formatFullDate(pkg.valid_until)} (parte vence em ${formatFullDate(pkg.next_expiry)})`
      : `válido até ${formatFullDate(pkg.valid_until)}`);

  const kpis = [
    {
      label: "Horas no período",
      value: hoursText(totals.hours),
      note: "Evolução e manutenção somadas",
      bg: PANEL,
      ink: SOFT_INK,
    },
    {
      label: "Evolução",
      value: hoursText(totals.evolution_hours),
      note: "Novas funcionalidades e mudanças pedidas",
      bg: KIND.evolution.kpi,
      ink: EVO,
    },
    {
      label: "Manutenção",
      value: hoursText(totals.maintenance_hours),
      note: "Incluídas no contrato, sem débito",
      bg: KIND.maintenance.kpi,
      ink: MAN,
    },
    {
      label: "Chamados concluídos",
      value: `${totals.done_items} de ${totals.items}`,
      note:
        totals.items === 0
          ? "Nenhum chamado no período"
          : open === 0
            ? "Todos concluídos"
            : `${open} ${open === 1 ? "segue" : "seguem"} em andamento`,
      bg: PANEL,
      ink: SOFT_INK,
    },
  ];

  const nextSteps = report.next_steps.map((step) =>
    step.type === "pending_estimate"
      ? `Orçamento de ${hoursText(step.hours)} enviado para "${step.title}" (${step.key}), aguardando aprovação.`
      : `${step.title}: em andamento (${step.key}).`
  );

  return (
    <div className="crp-doc" style={{ display: "flex", flexDirection: "column", gap: 24, alignItems: "center" }}>
      {/* Página 1: resumo */}
      <article aria-label="Resumo" className="crp-sheet">
        <header
          style={{
            padding: "44px 52px 28px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 24,
            borderBottom: `1px solid ${LINE}`,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 18, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 9,
                  background: INK,
                  color: "#FFFFFF",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 800,
                  fontSize: 17,
                }}
              >
                C
              </span>
              <span style={{ fontSize: 18, fontWeight: 800, letterSpacing: 0.2 }}>Conjo SA</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span
                style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.4, textTransform: "uppercase", color: FAINT }}
              >
                Relatório de atividades
              </span>
              <span style={{ fontSize: 28, fontWeight: 800, lineHeight: 1.15, overflowWrap: "anywhere" }}>
                {clientName}
              </span>
              <span style={{ fontSize: 14, color: MUTED }}>{period}</span>
            </div>
          </div>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto auto",
              gap: "6px 14px",
              fontSize: 12,
              textAlign: "right",
              flexShrink: 0,
            }}
          >
            <dt style={{ color: FAINT }}>Nº</dt>
            <dd style={{ fontFamily: MONO, fontWeight: 600 }}>{report.number}</dd>
            <dt style={{ color: FAINT }}>Emitido em</dt>
            <dd style={{ fontWeight: 600 }}>{issued}</dd>
            {report.contract && (
              <>
                <dt style={{ color: FAINT }}>Contrato</dt>
                <dd style={{ fontWeight: 600 }}>{report.contract.name}</dd>
              </>
            )}
            <dt style={{ color: FAINT }}>Responsável</dt>
            <dd style={{ fontWeight: 600 }}>{report.owner}</dd>
          </dl>
        </header>

        <section
          style={{ ...section(26), display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}
          className="crp-keep"
        >
          {kpis.map((kpi) => (
            <div
              key={kpi.label}
              style={{
                padding: "14px 14px 12px",
                borderRadius: 12,
                background: kpi.bg,
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <span style={{ fontSize: 11.5, fontWeight: 700, color: kpi.ink }}>{kpi.label}</span>
              <span style={{ fontSize: 26, fontWeight: 800, lineHeight: 1.1 }}>{kpi.value}</span>
              <span style={{ fontSize: 11, color: MUTED, lineHeight: 1.35 }}>{kpi.note}</span>
            </div>
          ))}
        </section>

        <section style={{ ...section(), display: "flex", flexDirection: "column", gap: 10 }} className="crp-keep">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
            <h2 style={h2}>Pacote de horas de evolução</h2>
            {pkg && (
              <span style={{ fontSize: 12, color: MUTED, textAlign: "right" }}>
                {hoursText(pkgUsed)} usadas de {hoursText(pkg.contracted)}
                {validity ? ` · ${validity}` : ""}
              </span>
            )}
          </div>
          {pkg ? (
            <>
              <div style={{ height: 14, borderRadius: 999, background: TRACK, overflow: "hidden", display: "flex" }}>
                <span style={{ width: pct(toHours(pkg.used_before), contracted), background: "#B9C9E6" }} />
                <span style={{ width: pct(toHours(pkg.used_in_period), contracted), background: EVO }} />
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 18, fontSize: 11.5, color: SOFT_INK }}>
                <Legend color="#B9C9E6">Meses anteriores {hoursText(pkg.used_before)}</Legend>
                <Legend color={EVO}>Este período {hoursText(pkg.used_in_period)}</Legend>
                <Legend color={TRACK} border>
                  Saldo {hoursText(pkg.balance)}
                </Legend>
                {toHours(pkg.excess_in_period) > 0 && (
                  <Legend color="#C2410C">Além do pacote {hoursText(pkg.excess_in_period)}</Legend>
                )}
              </div>
            </>
          ) : (
            <p style={{ fontSize: 12, color: MUTED }}>Sem pacote de horas de evolução no período.</p>
          )}
        </section>

        <section
          style={{ ...section(), display: "grid", gridTemplateColumns: "1fr 1fr", gap: 28 }}
          className="crp-keep"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <h2 style={h2}>Horas por tipo</h2>
            {report.by_kind.map((item) => (
              <div key={item.kind} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, fontWeight: 700 }}>
                  <span>{KIND[item.kind].label}</span>
                  <span>{hoursText(item.hours)}</span>
                </div>
                <div style={{ height: 8, borderRadius: 999, background: TRACK }}>
                  <div
                    style={{
                      width: pct(item.minutes, totals.minutes),
                      height: 8,
                      borderRadius: 999,
                      background: KIND[item.kind].color,
                    }}
                  />
                </div>
                <span style={{ fontSize: 11, color: MUTED }}>
                  {item.items === 0
                    ? "Nenhum chamado no período"
                    : `${plural(item.items, "chamado", "chamados")}, ${plural(item.done_items, "concluído", "concluídos")}`}
                </span>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <h2 style={h2}>Horas por sistema</h2>
            {report.by_system.length === 0 && (
              <p style={{ fontSize: 12, color: MUTED }}>Nenhuma hora registrada no período.</p>
            )}
            {report.by_system.map((system) => (
              <div
                key={system.name}
                style={{
                  display: "grid",
                  gridTemplateColumns: "110px 1fr 46px",
                  alignItems: "center",
                  gap: 10,
                  fontSize: 12.5,
                }}
              >
                <span style={{ fontWeight: 700, overflowWrap: "anywhere" }}>{system.name}</span>
                <div style={{ height: 8, borderRadius: 999, background: TRACK, display: "flex", overflow: "hidden" }}>
                  <span style={{ width: pct(system.evolution_minutes, system.minutes), background: EVO }} />
                  <span style={{ width: pct(system.maintenance_minutes, system.minutes), background: MAN }} />
                </div>
                <span style={{ textAlign: "right", fontWeight: 700 }}>{hoursText(system.hours)}</span>
              </div>
            ))}
          </div>
        </section>

        <section style={{ ...section(24), display: "flex", flexDirection: "column", gap: 10, paddingBottom: 24 }}>
          <h2 style={h2}>Principais entregas</h2>
          {report.highlights.length === 0 && (
            <p style={{ fontSize: 12, color: MUTED }}>Nenhuma entrega registrada no período.</p>
          )}
          {report.highlights.map((item) => (
            <div
              key={item.key}
              className="crp-keep"
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                gap: "4px 14px",
                padding: "12px 14px",
                borderRadius: 12,
                border: `1px solid ${LINE}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <Tag kind={item.kind} />
                <span style={{ fontSize: 13.5, fontWeight: 800, overflowWrap: "anywhere" }}>{item.title}</span>
              </div>
              <span style={{ fontSize: 12.5, fontWeight: 700, color: SOFT_INK }}>{hoursText(item.hours)}</span>
              {item.summary && (
                <span style={{ gridColumn: "1 / -1", fontSize: 12, lineHeight: 1.45, color: "#4A4A45" }}>
                  {item.summary}
                </span>
              )}
            </div>
          ))}
        </section>

        <Footer>
          <span>Conjo SA · contato@conjosa.com.br · conjosa.com.br</span>
        </Footer>
      </article>

      {/* Página 2: detalhamento */}
      <article aria-label="Detalhamento" className="crp-sheet">
        <header
          style={{
            padding: "36px 52px 18px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: 16,
            borderBottom: `1px solid ${LINE}`,
          }}
        >
          <span style={{ fontSize: 18, fontWeight: 800 }}>Detalhamento das atividades</span>
          <span style={{ fontSize: 12, color: MUTED, textAlign: "right" }}>
            {clientName} · {period}
          </span>
        </header>

        <section style={section(14)}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr
                style={{
                  textAlign: "left",
                  color: FAINT,
                  fontSize: 10.5,
                  textTransform: "uppercase",
                  letterSpacing: 0.6,
                }}
              >
                <th style={{ padding: "8px 6px 8px 0", fontWeight: 700, width: 46 }}>Data</th>
                <th style={{ padding: "8px 6px", fontWeight: 700, width: 72 }}>Chamado</th>
                <th style={{ padding: "8px 6px", fontWeight: 700, width: 78 }}>Tipo</th>
                <th style={{ padding: "8px 6px", fontWeight: 700 }}>O que foi feito</th>
                <th style={{ padding: "8px 0 8px 6px", fontWeight: 700, width: 48, textAlign: "right" }}>Horas</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.length === 0 && (
                <tr style={{ borderTop: "1px solid #F0F0EC" }}>
                  <td colSpan={5} style={{ padding: "12px 0", color: MUTED }}>
                    Nenhuma hora registrada no período.
                  </td>
                </tr>
              )}
              {report.rows.map((row) => (
                <tr key={row.id} style={{ borderTop: "1px solid #F0F0EC", verticalAlign: "top" }}>
                  <td style={{ padding: "8px 6px 8px 0", color: MUTED }}>{dayMonth(row.date)}</td>
                  <td style={{ padding: "8px 6px", fontFamily: MONO, fontWeight: 600, fontSize: 10.5 }}>{row.key}</td>
                  <td style={{ padding: "8px 6px" }}>
                    <Tag kind={row.kind} small />
                  </td>
                  <td style={{ padding: "8px 6px", lineHeight: 1.45, overflowWrap: "anywhere" }}>
                    <b style={{ fontWeight: 700 }}>{/[.!?]$/.test(row.title) ? row.title : `${row.title}.`}</b>
                    {row.description ? ` ${row.description}` : ""}
                  </td>
                  <td style={{ padding: "8px 0 8px 6px", textAlign: "right", fontWeight: 700, whiteSpace: "nowrap" }}>
                    {hoursText(row.hours)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot style={{ display: "table-row-group" }}>
              {[
                { label: "Evolução", hours: totals.evolution_hours, weight: 600 },
                { label: "Manutenção (incluída no contrato)", hours: totals.maintenance_hours, weight: 600 },
                { label: "Total do período", hours: totals.hours, weight: 800 },
              ].map((total) => (
                <tr key={total.label} style={{ borderTop: "1px solid #E4E4E0" }}>
                  <td
                    colSpan={4}
                    style={{ padding: "8px 6px 8px 0", textAlign: "right", fontWeight: total.weight, color: SOFT_INK }}
                  >
                    {total.label}
                  </td>
                  <td style={{ padding: "8px 0 8px 6px", textAlign: "right", fontWeight: 800, whiteSpace: "nowrap" }}>
                    {hoursText(total.hours)}
                  </td>
                </tr>
              ))}
            </tfoot>
          </table>
        </section>

        <section
          style={{ ...section(20), display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, paddingBottom: 24 }}
          className="crp-keep"
        >
          <div
            style={{
              padding: "14px 16px",
              borderRadius: 12,
              background: PANEL,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <h2 style={{ ...h2, fontSize: 13 }}>Em andamento e próximos passos</h2>
            {nextSteps.length === 0 && (
              <p style={{ fontSize: 12, lineHeight: 1.45 }}>Nenhum chamado em aberto no momento.</p>
            )}
            {nextSteps.map((text) => (
              <div key={text} style={{ display: "flex", gap: 8, fontSize: 12, lineHeight: 1.45 }}>
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 999,
                    background: SOFT_INK,
                    marginTop: 6,
                    flexShrink: 0,
                  }}
                />
                <span style={{ overflowWrap: "anywhere" }}>{text}</span>
              </div>
            ))}
          </div>
          <div
            style={{
              padding: "14px 16px",
              borderRadius: 12,
              background: PANEL,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <h2 style={{ ...h2, fontSize: 13 }}>Como as horas são contadas</h2>
            <p style={{ fontSize: 11.5, lineHeight: 1.5, color: SOFT_INK }}>
              <b style={{ color: EVO }}>Evolução</b> é tudo o que acrescenta ou muda funcionalidade a pedido do cliente
              e é debitado do pacote contratado, depois de orçamento aprovado.
            </p>
            <p style={{ fontSize: 11.5, lineHeight: 1.5, color: SOFT_INK }}>
              <b style={{ color: MAN }}>Manutenção</b> é correção de erro, segurança e estabilidade. Está incluída no
              contrato e não é debitada.
            </p>
          </div>
        </section>

        <Footer>
          <span>Gerado pelo Tasks em {issued}. Cada linha corresponde a um lançamento de horas do chamado.</span>
        </Footer>
      </article>
    </div>
  );
}
