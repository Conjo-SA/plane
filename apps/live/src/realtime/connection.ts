/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { IncomingMessage } from "http";
import type { WebSocket } from "ws";
import { logger } from "@plane/logger";
import type { RealtimeAccessService } from "./access";
import type { RealtimeHub } from "./hub";
import { RealtimeClient } from "./hub";
import { isAllowedOrigin } from "./origin";
import { parseClientMessage } from "./protocol";

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_FORBIDDEN_ORIGIN = 4403;
export const CLOSE_TOO_MANY_CONNECTIONS = 4429;
export const CLOSE_UNAVAILABLE = 4503;

const HEARTBEAT_INTERVAL_MS = 30_000;
/** Memberships are checked again periodically, so someone removed from a project stops hearing about it. */
const REVALIDATE_INTERVAL_MS = 5 * 60_000;
/** Too many malformed messages: not our client. */
const MAX_INVALID_MESSAGES = 20;

type TDeps = {
  hub: RealtimeHub;
  access: RealtimeAccessService;
  allowedOrigins: string[];
};

const headerValue = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export const handleRealtimeConnection = async (ws: WebSocket, req: IncomingMessage, deps: TDeps) => {
  const { hub, access, allowedOrigins } = deps;

  const origin = headerValue(req.headers.origin);
  const forwardedHost = headerValue(req.headers["x-forwarded-host"]);
  const sameSite =
    isAllowedOrigin(origin, req.headers.host, allowedOrigins) ||
    (!!forwardedHost && isAllowedOrigin(origin, forwardedHost, allowedOrigins));
  if (!sameSite) {
    ws.close(CLOSE_FORBIDDEN_ORIGIN, "Origin not allowed");
    return;
  }

  // Messages that arrive while the session is being checked are dropped: the browser only
  // sends joins after the "ready" message.
  let client: RealtimeClient | null = null;
  let closed = false;
  let invalidMessages = 0;
  let alive = true;
  const timers: NodeJS.Timeout[] = [];

  const cleanup = () => {
    if (closed) return;
    closed = true;
    timers.forEach((timer) => clearInterval(timer));
    if (client) hub.unregister(client);
  };
  ws.on("close", cleanup);
  ws.on("error", (error: Error) => {
    logger.warn("REALTIME: WebSocket error", error);
    cleanup();
  });

  const cookie = headerValue(req.headers.cookie) ?? "";
  if (!cookie) {
    ws.close(CLOSE_UNAUTHENTICATED, "Unauthenticated");
    return;
  }

  const userId = await access.currentUserId(cookie);
  if (closed) return;
  if (userId === "unavailable") {
    ws.close(CLOSE_UNAVAILABLE, "API unavailable");
    return;
  }
  if (!userId) {
    ws.close(CLOSE_UNAUTHENTICATED, "Unauthenticated");
    return;
  }

  const authenticated = new RealtimeClient(ws, userId, cookie);
  if (!hub.register(authenticated)) {
    ws.close(CLOSE_TOO_MANY_CONNECTIONS, "Too many connections");
    return;
  }
  client = authenticated;

  const join = async (workspaceSlug: string, projectId: string) => {
    if (!hub.allowJoin(authenticated)) {
      authenticated.send({ type: "join_error", project_id: projectId, code: "rate_limited" });
      return;
    }
    const result = await access.projectAccess(cookie, workspaceSlug, projectId);
    if (closed) return;
    if (result.status === "unauthenticated" || (result.status === "allowed" && result.userId !== userId)) {
      ws.close(CLOSE_UNAUTHENTICATED, "Unauthenticated");
      return;
    }
    if (result.status !== "allowed") {
      hub.leave(authenticated, projectId);
      authenticated.send({ type: "join_error", project_id: projectId, code: result.status });
      return;
    }
    if (hub.join(authenticated, projectId, { workspaceSlug, restricted: result.restricted }) !== "joined") {
      authenticated.send({ type: "join_error", project_id: projectId, code: "too_many_rooms" });
      return;
    }
    authenticated.send({ type: "joined", project_id: projectId });
  };

  ws.on("message", (raw: unknown) => {
    const message = parseClientMessage(raw);
    if (!message) {
      invalidMessages += 1;
      if (invalidMessages > MAX_INVALID_MESSAGES) ws.close(1008, "Invalid messages");
      return;
    }
    if (message.type === "ping") {
      authenticated.send({ type: "pong" });
      return;
    }
    if (message.type === "leave") {
      hub.leave(authenticated, message.project_id);
      return;
    }
    void join(message.workspace_slug, message.project_id).catch((error) => logger.warn("REALTIME: join failed", error));
  });

  // Heartbeat: half-open connections (laptop lid closed, network gone) are dropped.
  ws.on("pong", () => {
    alive = true;
  });
  timers.push(
    setInterval(() => {
      if (!alive) {
        ws.terminate();
        cleanup();
        return;
      }
      alive = false;
      try {
        ws.ping();
      } catch {
        // close handler cleans up
      }
    }, HEARTBEAT_INTERVAL_MS)
  );

  // Re-check every membership (and the session) from time to time.
  const revalidate = async (projectId: string, workspaceSlug: string) => {
    const result = await access.projectAccess(cookie, workspaceSlug, projectId);
    if (closed) return;
    if (result.status === "unauthenticated") {
      ws.close(CLOSE_UNAUTHENTICATED, "Unauthenticated");
    } else if (result.status === "forbidden") {
      hub.leave(authenticated, projectId);
      authenticated.send({ type: "left", project_id: projectId, code: "forbidden" });
    } else if (result.status === "allowed" && authenticated.rooms.has(projectId)) {
      authenticated.rooms.set(projectId, { workspaceSlug, restricted: result.restricted });
    }
  };
  timers.push(
    setInterval(() => {
      for (const [projectId, membership] of Array.from(authenticated.rooms.entries())) {
        revalidate(projectId, membership.workspaceSlug).catch(() => undefined);
      }
    }, REVALIDATE_INTERVAL_MS)
  );

  authenticated.send({ type: "ready" });
};
