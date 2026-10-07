/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { action, makeObservable, observable } from "mobx";
import { LIVE_BASE_PATH, LIVE_BASE_URL } from "@plane/constants";

export type TRealtimeStatus = "idle" | "connecting" | "connected" | "reconnecting";

/** What the live server relays: ids and field names only (the data comes from the API). */
export type TRealtimeEvent = {
  type: string;
  workspace_slug: string;
  project_id: string;
  issue_ids: string[];
  actor_id?: string | null;
  fields: string[];
  ts?: number;
};

type TServerMessage =
  | { type: "ready" }
  | { type: "pong" }
  | { type: "joined"; project_id: string }
  | { type: "join_error"; project_id: string; code: string }
  | { type: "left"; project_id: string; code: string }
  | { type: "event"; event: TRealtimeEvent };

type TRoom = { workspaceSlug: string; refs: number; joined: boolean; joinedOnce: boolean };

export type TRealtimeListener = {
  onEvent: (event: TRealtimeEvent) => void;
  /** Called after a reconnection rejoined the room: events may have been missed meanwhile. */
  onResync: (workspaceSlug: string, projectId: string) => void;
};

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;
const PING_INTERVAL_MS = 25_000;
/** Codes the server uses when retrying would not help (no session, foreign origin). */
const FATAL_CLOSE_CODES = new Set([4401, 4403]);
const FATAL_RETRY_MS = 60_000;
const IDLE_DISCONNECT_MS = 10_000;

/** Builds the realtime socket URL the same way the page editor builds its collaboration URL. */
export const getRealtimeUrl = () => {
  const base = LIVE_BASE_URL?.trim() || window.location.origin;
  const url = new URL(base);
  url.protocol = window.location.protocol === "https:" ? "wss" : "ws";
  url.pathname = `${LIVE_BASE_PATH}/realtime`;
  url.search = "";
  return url.toString();
};

/**
 * One WebSocket per tab to the live server, shared by every project screen. It joins the rooms
 * that are in use, reconnects with exponential backoff and rejoins afterwards.
 */
export class RealtimeConnection {
  status: TRealtimeStatus = "idle";

  private socket: WebSocket | null = null;
  private ready = false;
  private readonly rooms = new Map<string, TRoom>();
  private readonly listeners = new Set<TRealtimeListener>();
  private attempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private hadConnection = false;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    makeObservable<RealtimeConnection, "setStatus">(this, {
      status: observable.ref,
      setStatus: action,
    });
    if (typeof window !== "undefined") {
      window.addEventListener("online", this.reconnectNow);
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") this.reconnectNow();
      });
    }
  }

  private setStatus(status: TRealtimeStatus) {
    this.status = status;
  }

  subscribe(listener: TRealtimeListener) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Follows a project while the returned function is not called. */
  joinProject(workspaceSlug: string, projectId: string) {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
    const room = this.rooms.get(projectId);
    if (room) room.refs += 1;
    else this.rooms.set(projectId, { workspaceSlug, refs: 1, joined: false, joinedOnce: false });
    if (this.ready) this.sendJoin(projectId);
    else this.ensureConnected();

    let released = false;
    return () => {
      if (released) return;
      released = true;
      const current = this.rooms.get(projectId);
      if (!current) return;
      current.refs -= 1;
      if (current.refs > 0) return;
      this.rooms.delete(projectId);
      this.send({ type: "leave", project_id: projectId });
      // navigating between projects leaves one room and joins another: keep the socket a moment
      if (this.rooms.size === 0 && !this.idleTimer) {
        this.idleTimer = setTimeout(() => {
          this.idleTimer = null;
          if (this.rooms.size === 0) this.disconnect();
        }, IDLE_DISCONNECT_MS);
      }
    };
  }

  private ensureConnected() {
    if (typeof window === "undefined" || typeof WebSocket === "undefined") return;
    if (this.socket || this.reconnectTimer || this.rooms.size === 0) return;
    this.connect();
  }

  private connect() {
    let socket: WebSocket;
    try {
      socket = new WebSocket(getRealtimeUrl());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    this.ready = false;
    this.setStatus(this.hadConnection ? "reconnecting" : "connecting");

    socket.addEventListener("message", (message) => this.handleMessage(socket, message.data));
    socket.addEventListener("close", (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.ready = false;
      this.stopPing();
      this.rooms.forEach((room) => (room.joined = false));
      if (this.rooms.size === 0) {
        this.setStatus("idle");
        return;
      }
      this.scheduleReconnect(FATAL_CLOSE_CODES.has(event.code) ? FATAL_RETRY_MS : undefined);
    });
    // "error" is always followed by "close", which schedules the reconnection
  }

  private handleMessage(socket: WebSocket, data: unknown) {
    if (this.socket !== socket || typeof data !== "string") return;
    let message: TServerMessage;
    try {
      message = JSON.parse(data) as TServerMessage;
    } catch {
      return;
    }
    switch (message.type) {
      case "ready":
        this.ready = true;
        this.attempts = 0;
        this.hadConnection = true;
        this.setStatus("connected");
        this.startPing();
        this.rooms.forEach((_room, projectId) => this.sendJoin(projectId));
        break;
      case "joined": {
        const room = this.rooms.get(message.project_id);
        if (!room) break;
        room.joined = true;
        if (room.joinedOnce)
          this.listeners.forEach((listener) => listener.onResync(room.workspaceSlug, message.project_id));
        room.joinedOnce = true;
        break;
      }
      case "event":
        if (message.event && this.rooms.has(message.event.project_id)) {
          this.listeners.forEach((listener) => listener.onEvent(message.event));
        }
        break;
      default:
        break;
    }
  }

  private sendJoin(projectId: string) {
    const room = this.rooms.get(projectId);
    if (!room) return;
    this.send({ type: "join", workspace_slug: room.workspaceSlug, project_id: projectId });
  }

  private send(message: Record<string, unknown>) {
    if (!this.socket || !this.ready || this.socket.readyState !== WebSocket.OPEN) return;
    try {
      this.socket.send(JSON.stringify(message));
    } catch {
      // onclose handles it
    }
  }

  private startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => this.send({ type: "ping" }), PING_INTERVAL_MS);
  }

  private stopPing() {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private scheduleReconnect(delay?: number) {
    if (this.reconnectTimer) return;
    this.attempts += 1;
    const backoff = Math.min(MAX_BACKOFF_MS, MIN_BACKOFF_MS * 2 ** Math.min(this.attempts - 1, 5));
    const wait = delay ?? backoff * (0.75 + Math.random() * 0.5);
    this.setStatus(this.hadConnection ? "reconnecting" : "connecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.rooms.size > 0) this.connect();
    }, wait);
  }

  /** Back online or back to the tab: try now instead of waiting for the backoff. */
  private reconnectNow = () => {
    if (this.socket || this.rooms.size === 0) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.connect();
  };

  private disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.stopPing();
    const socket = this.socket;
    this.socket = null;
    this.ready = false;
    socket?.close(1000);
    this.setStatus("idle");
  }
}

export const realtimeConnection = new RealtimeConnection();
