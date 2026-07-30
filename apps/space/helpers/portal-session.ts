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
