/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** Decimal hours ("1.50" or 1.5) to minutes. */
export const hoursToMinutes = (hours: string | number | null | undefined): number => {
  const value = typeof hours === "number" ? hours : parseFloat(hours ?? "");
  return Number.isFinite(value) ? Math.round(value * 60) : 0;
};

/** 390 → "6h30", 120 → "2h", 45 → "45min". Negative values keep the sign. */
export function formatMinutes(minutes: number): string {
  const sign = minutes < 0 ? "−" : "";
  const total = Math.round(Math.abs(minutes));
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours === 0 && rest > 0) return `${sign}${rest}min`;
  if (rest === 0) return `${sign}${hours}h`;
  return `${sign}${hours}h${String(rest).padStart(2, "0")}`;
}

/** "8.00" → "8h", "1.50" → "1h30". */
export const formatHours = (hours: string | number | null | undefined): string => formatMinutes(hoursToMinutes(hours));

/** "2026-11-30" → "30/11", read without a timezone shift. */
export function formatDayMonth(value: string | null | undefined): string {
  if (!value) return "";
  const plain = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return plain ? `${plain[3]}/${plain[2]}` : "";
}
