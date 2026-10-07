/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { ConjoBillingService } from "@plane/services";
import type { THourLedgerKind, TIssueRef, TWorkKind } from "@plane/types";

export const conjoBillingService = new ConjoBillingService();

// SWR keys, shared by the pages and the header breadcrumbs.
export const clientsKey = (workspaceSlug: string) => `CONJO_CLIENTS_${workspaceSlug}`;
export const clientKey = (workspaceSlug: string, clientId: string) => `CONJO_CLIENT_${workspaceSlug}_${clientId}`;
export const clientLabelOptionsKey = (workspaceSlug: string) => `CONJO_CLIENT_LABEL_OPTIONS_${workspaceSlug}`;

/** The API answers errors as `{ error: "<mensagem pt-BR>" }`; the service rethrows the axios response. */
export const getErrorMessage = (err: unknown, fallback: string): string =>
  (err as { data?: { error?: string } } | undefined)?.data?.error || fallback;

const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MONTHS_LONG = [
  "janeiro",
  "fevereiro",
  "março",
  "abril",
  "maio",
  "junho",
  "julho",
  "agosto",
  "setembro",
  "outubro",
  "novembro",
  "dezembro",
];

const pad = (value: number) => String(value).padStart(2, "0");

/** Parses "YYYY-MM-DD" as a local date (new Date("YYYY-MM-DD") would be UTC midnight, the day before in Brazil). */
export const parseDateOnly = (value: string): Date | null => {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
};

/** "YYYY-MM-DD" of a local date, as the API and `<input type="date">` expect. */
export const toISODate = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

/** "YYYY-MM-DDTHH:mm" for `<input type="datetime-local">`. */
export const toLocalDateTimeInput = (date: Date) =>
  `${toISODate(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;

/** ISO datetime with the local offset ("2026-10-06T14:30:00-03:00"), which Python's fromisoformat accepts. */
export const toISODateTimeWithOffset = (date: Date) => {
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return `${toLocalDateTimeInput(date)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
};

const parseAny = (value: string): Date | null => {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return parseDateOnly(value);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

/** Decimal hours ("8.00", "-1.50") as a number. */
export const toHours = (value: string | number | null | undefined): number => {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
};

/** "8.00" → "8h", "1.50" → "1h30", "0.50" → "30min". The sign is dropped; see formatSignedHours. */
export const formatHours = (value: string | number | null | undefined): string => {
  const totalMinutes = Math.round(Math.abs(toHours(value)) * 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0 && minutes > 0) return `${minutes}min`;
  return minutes ? `${hours}h${pad(minutes)}` : `${hours}h`;
};

export const formatMinutes = (minutes: number): string => formatHours(minutes / 60);

/** "+20h", "−8h" (typographic minus). */
export const formatSignedHours = (value: string | number): string => {
  const hours = toHours(value);
  if (hours === 0) return "0h";
  return `${hours > 0 ? "+" : "−"}${formatHours(hours)}`;
};

/** dd/mm, with the year when it is not the current one. */
export const formatDayMonth = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = parseAny(value);
  if (!date) return value;
  const base = `${pad(date.getDate())}/${pad(date.getMonth() + 1)}`;
  return date.getFullYear() === new Date().getFullYear() ? base : `${base}/${String(date.getFullYear()).slice(2)}`;
};

export const formatFullDate = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = parseAny(value);
  return date ? `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()}` : value;
};

/** "mm/yyyy", for "cliente desde 03/2025". */
export const formatMonthYear = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = parseAny(value);
  return date ? `${pad(date.getMonth() + 1)}/${date.getFullYear()}` : value;
};

export const formatTime = (value: string): string => {
  const date = parseAny(value);
  return date ? `${pad(date.getHours())}:${pad(date.getMinutes())}` : "";
};

/** Lot period "2026-09-01" → "set/26". */
export const formatLotPeriod = (value: string | null | undefined): string => {
  const date = value ? parseDateOnly(value) : null;
  return date ? `${MONTHS_SHORT[date.getMonth()]}/${String(date.getFullYear()).slice(2)}` : "";
};

/** "2026-09-01" → "setembro". */
export const formatMonthName = (value: string | Date | null | undefined): string => {
  const date = value instanceof Date ? value : value ? parseDateOnly(value) : null;
  return date ? MONTHS_LONG[date.getMonth()] : "";
};

/** Local day key ("YYYY-MM-DD") of an ISO datetime, to group timeline events by day. */
export const dayKey = (value: string): string => {
  const date = parseAny(value);
  return date ? toISODate(date) : value;
};

/** "Hoje", "Ontem" or dd/mm for a day key. */
export const formatDayLabel = (key: string): string => {
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (key === toISODate(today)) return "Hoje";
  if (key === toISODate(yesterday)) return "Ontem";
  return formatDayMonth(key);
};

/** Last day of the month that is `monthsAhead` months after `date`'s month. */
export const endOfMonth = (date: Date, monthsAhead = 0) =>
  new Date(date.getFullYear(), date.getMonth() + monthsAhead + 1, 0);

export const issueHref = (workspaceSlug: string, issue: TIssueRef) => `/${workspaceSlug}/browse/${issue.key}/`;

export const WORK_KIND_LABEL: Record<TWorkKind, string> = {
  evolution: "Evolução",
  maintenance: "Manutenção",
  internal: "Interno",
};

export const LEDGER_KIND_LABEL: Record<THourLedgerKind, string> = {
  credit: "Crédito",
  debit: "Débito",
  expiration: "Expiração",
  reversal: "Estorno",
  adjustment: "Ajuste",
  excess: "Excedente",
};

/** Chip/badge colors per ledger kind (mockup: credit green, debit strong, expiration amber, excess red). */
export const LEDGER_KIND_CLASS: Record<THourLedgerKind, string> = {
  credit: "bg-success-subtle text-success-primary",
  debit: "bg-inverse text-inverse",
  expiration: "bg-warning-subtle text-warning-primary",
  reversal: "bg-layer-3 text-secondary",
  adjustment: "bg-accent-subtle text-accent-primary",
  excess: "bg-danger-subtle text-danger-primary",
};

/** Bar colors for the lots, the one that expires first first. */
export const LOT_BAR_CLASSES = ["bg-warning-primary", "bg-inverse", "bg-accent-primary", "bg-success-primary"];

export const lotBarClass = (index: number) => LOT_BAR_CLASSES[index % LOT_BAR_CLASSES.length];

/** Percentage (0–100) of `part` in `total`, safe for zero totals. */
export const percentOf = (part: string | number, total: string | number) => {
  const max = toHours(total);
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (toHours(part) / max) * 100));
};

export const initialOf = (name: string) => name.trim().charAt(0).toUpperCase() || "?";

/** "Maria", "Maria e João", "Maria, João e Ana". */
export const joinNames = (names: string[]) =>
  names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} e ${names[names.length - 1]}`;
