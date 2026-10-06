/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** 390 → "6h30", 120 → "2h", 45 → "45min", 0 → "0h". Negative values keep the sign. */
export function formatMinutes(minutes: number): string {
  const sign = minutes < 0 ? "−" : "";
  const total = Math.round(Math.abs(minutes));
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours === 0 && rest > 0) return `${sign}${rest}min`;
  if (rest === 0) return `${sign}${hours}h`;
  return `${sign}${hours}h${String(rest).padStart(2, "0")}`;
}

/** Decimal hours as sent by the API ("1.50") to minutes. */
export const hoursToMinutes = (hours: string | number | null | undefined): number => {
  const value = typeof hours === "number" ? hours : parseFloat(hours ?? "");
  return Number.isFinite(value) ? Math.round(value * 60) : 0;
};

/** "8.00" → "8h", "1.50" → "1h30". */
export const formatHours = (hours: string | number | null | undefined): string => formatMinutes(hoursToMinutes(hours));

/** "2026-10-06" (or an ISO datetime) → "06/10". Plain dates are read without a timezone shift. */
export function formatDayMonth(value: string | null | undefined): string {
  if (!value) return "";
  const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (plain) return `${plain[3]}/${plain[2]}`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Today in the local timezone as "YYYY-MM-DD", for date inputs. */
export function todayISO(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
