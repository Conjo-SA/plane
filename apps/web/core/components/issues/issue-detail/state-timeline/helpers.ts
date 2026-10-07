/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Compact duration: "2d 4h", "3h 20min", "12min", "<1min". */
export const formatDuration = (seconds: number): string => {
  const value = Math.max(0, Math.floor(seconds));
  if (value < MINUTE) return "<1min";
  const days = Math.floor(value / DAY);
  const hours = Math.floor((value % DAY) / HOUR);
  const minutes = Math.floor((value % HOUR) / MINUTE);
  if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}min` : `${hours}h`;
  return `${minutes}min`;
};

export const secondsSince = (iso: string | null | undefined, now: number): number =>
  iso ? Math.max(0, (now - new Date(iso).getTime()) / 1000) : 0;

export const formatDateTime = (iso: string): string =>
  new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

// One shared clock for every counter on screen, instead of a timer per card.
const listeners = new Set<(now: number) => void>();
let timer: ReturnType<typeof setInterval> | undefined;

const subscribe = (listener: (now: number) => void, intervalMs: number) => {
  listeners.add(listener);
  if (!timer) timer = setInterval(() => listeners.forEach((notify) => notify(Date.now())), intervalMs);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
};

/** Current time, refreshed every minute: keeps the counters ticking. */
export const useNow = (): number => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => subscribe(setNow, 60_000), []);
  return now;
};
