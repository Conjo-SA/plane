/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

const toOrigin = (value: string): string | null => {
  try {
    const url = new URL(value.trim());
    return `${url.protocol}//${url.host}`.toLowerCase();
  } catch {
    return null;
  }
};

/** Origins allowed besides the live server's own host: CORS_ALLOWED_ORIGINS, WEB_BASE_URL, APP_BASE_URL. */
export const configuredOrigins = (env: Record<string, string | undefined>): string[] =>
  [...(env.CORS_ALLOWED_ORIGINS ?? "").split(","), env.WEB_BASE_URL ?? "", env.APP_BASE_URL ?? ""]
    .map((value) => (value.trim() ? toOrigin(value) : null))
    .filter((value): value is string => !!value);

/**
 * Blocks cross-site WebSocket hijacking: a page on another site cannot open the realtime socket
 * with the user's cookies. Same host (production: web and live behind the same proxy) or an
 * explicitly configured origin is accepted. Requests without Origin are not from a browser page.
 */
export const isAllowedOrigin = (
  origin: string | undefined,
  host: string | undefined,
  allowedOrigins: string[]
): boolean => {
  if (!origin) return true;
  const normalized = toOrigin(origin);
  if (!normalized) return false;
  if (allowedOrigins.includes(normalized)) return true;
  if (!host) return false;
  try {
    return new URL(normalized).host === host.trim().toLowerCase();
  } catch {
    return false;
  }
};
