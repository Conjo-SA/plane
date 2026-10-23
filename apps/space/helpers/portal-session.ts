/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

const STORAGE_PREFIX = "plane-portal-session";

export type TPortalSession = {
    token: string;
    email: string;
};

const storageKey = (anchor: string) => `${STORAGE_PREFIX}-${anchor}`;

/**
 * Reads the stored requester session for a portal.
 * Sessions are per anchor so different portals never share credentials.
 */
export const getPortalSession = (anchor: string): TPortalSession | null => {
    if (typeof window === "undefined") return null;
    try {
        const raw = window.localStorage.getItem(storageKey(anchor));
        if (!raw) return null;
        const parsed = JSON.parse(raw) as TPortalSession;
        return parsed?.token && parsed?.email ? parsed : null;
    } catch {
        return null;
    }
};

export const setPortalSession = (anchor: string, session: TPortalSession): void => {
    if (typeof window === "undefined") return;
    try {
        window.localStorage.setItem(storageKey(anchor), JSON.stringify(session));
    } catch {
        // storage can be unavailable in private mode, the session simply won't persist
    }
};

export const clearPortalSession = (anchor: string): void => {
    if (typeof window === "undefined") return;
    try {
        window.localStorage.removeItem(storageKey(anchor));
    } catch {
        // nothing to clean up
    }
};

// Conjo (MAN-363): the backend answers 401 when the stored token no longer has an active session.
// The pages must then drop the session (state and storage) and send the requester back to the login.

const EXPIRED_FLAG_PREFIX = "plane-portal-session-expired";

const expiredFlagKey = (anchor: string) => `${EXPIRED_FLAG_PREFIX}-${anchor}`;

export const PORTAL_SESSION_EXPIRED_MESSAGE = "Sua sessão expirou. Entre novamente.";

/** True when an error thrown by the intake portal service means the session token is no longer valid. */
export const isPortalSessionExpired = (err: unknown): boolean =>
    (err as { status?: number } | null | undefined)?.status === 401;

/**
 * Forgets the expired session of a portal and remembers (for this tab only) that it expired,
 * so the login screen of the same portal can tell the requester why they were signed out.
 * Only the expired token is removed: a newer login (e.g. made in another tab) is kept.
 */
export const expirePortalSession = (anchor: string, expiredToken: string): void => {
    if (getPortalSession(anchor)?.token === expiredToken) clearPortalSession(anchor);
    if (typeof window === "undefined") return;
    try {
        window.sessionStorage.setItem(expiredFlagKey(anchor), "1");
    } catch {
        // without storage the login screen simply won't show the notice
    }
};

/** Reads and clears the "session expired" notice left by `expirePortalSession` for this portal. */
export const consumePortalSessionExpired = (anchor: string): boolean => {
    if (typeof window === "undefined") return false;
    try {
        const key = expiredFlagKey(anchor);
        const expired = window.sessionStorage.getItem(key) === "1";
        if (expired) window.sessionStorage.removeItem(key);
        return expired;
    } catch {
        return false;
    }
};
