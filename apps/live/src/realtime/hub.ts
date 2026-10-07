/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TPublishedEvent, TRealtimeEvent } from "./protocol";

/** The part of a WebSocket the hub needs (kept small so it is easy to test). */
export type TRealtimeSocket = {
  readonly readyState: number;
  readonly bufferedAmount?: number;
  send(data: string): void;
};

export type TRoomMembership = {
  workspaceSlug: string;
  /** Guests who only see the work items they created. */
  restricted: boolean;
};

export type TRealtimeHubOptions = {
  maxRoomsPerClient: number;
  maxJoinsPerWindow: number;
  joinWindowMs: number;
  maxClientsPerUser: number;
  /** Slow consumers (a lot of unsent data) are skipped instead of buffering forever. */
  maxBufferedBytes: number;
};

const DEFAULT_OPTIONS: TRealtimeHubOptions = {
  maxRoomsPerClient: 5,
  maxJoinsPerWindow: 30,
  joinWindowMs: 60_000,
  maxClientsPerUser: 30,
  maxBufferedBytes: 1_000_000,
};

const WS_OPEN = 1;

export class RealtimeClient {
  readonly rooms = new Map<string, TRoomMembership>();
  private joinTimestamps: number[] = [];

  constructor(
    readonly socket: TRealtimeSocket,
    readonly userId: string,
    readonly cookie: string
  ) {}

  /** Sliding-window rate limit for joins. Records the attempt when allowed. */
  allowJoin(now: number, maxJoins: number, windowMs: number): boolean {
    this.joinTimestamps = this.joinTimestamps.filter((timestamp) => now - timestamp < windowMs);
    if (this.joinTimestamps.length >= maxJoins) return false;
    this.joinTimestamps.push(now);
    return true;
  }

  send(message: unknown): boolean {
    if (this.socket.readyState !== WS_OPEN) return false;
    try {
      this.socket.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }
}

export type TJoinResult = "joined" | "too_many_rooms";

/**
 * In-memory rooms: project id -> connected browsers. One instance per live server; when Redis is
 * configured, events reach every instance through pub/sub and each one broadcasts to its own rooms.
 */
export class RealtimeHub {
  private readonly rooms = new Map<string, Set<RealtimeClient>>();
  private readonly clientsByUser = new Map<string, Set<RealtimeClient>>();
  readonly options: TRealtimeHubOptions;

  constructor(options: Partial<TRealtimeHubOptions> = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  /** Registers an authenticated connection. False when the user already has too many open. */
  register(client: RealtimeClient): boolean {
    const clients = this.clientsByUser.get(client.userId) ?? new Set<RealtimeClient>();
    if (clients.size >= this.options.maxClientsPerUser) return false;
    clients.add(client);
    this.clientsByUser.set(client.userId, clients);
    return true;
  }

  unregister(client: RealtimeClient) {
    for (const projectId of Array.from(client.rooms.keys())) this.leave(client, projectId);
    const clients = this.clientsByUser.get(client.userId);
    if (clients) {
      clients.delete(client);
      if (clients.size === 0) this.clientsByUser.delete(client.userId);
    }
  }

  allowJoin(client: RealtimeClient, now = Date.now()): boolean {
    return client.allowJoin(now, this.options.maxJoinsPerWindow, this.options.joinWindowMs);
  }

  join(client: RealtimeClient, projectId: string, membership: TRoomMembership): TJoinResult {
    if (!client.rooms.has(projectId) && client.rooms.size >= this.options.maxRoomsPerClient) return "too_many_rooms";
    client.rooms.set(projectId, membership);
    const room = this.rooms.get(projectId) ?? new Set<RealtimeClient>();
    room.add(client);
    this.rooms.set(projectId, room);
    return "joined";
  }

  leave(client: RealtimeClient, projectId: string) {
    client.rooms.delete(projectId);
    const room = this.rooms.get(projectId);
    if (!room) return;
    room.delete(client);
    if (room.size === 0) this.rooms.delete(projectId);
  }

  /** Sends the event to everyone in the project's room. Returns how many browsers got it. */
  broadcast(event: TPublishedEvent): number {
    const room = this.rooms.get(event.project_id);
    if (!room || room.size === 0) return 0;

    const { issue_creators: issueCreators = {}, ...publicEvent } = event;
    const fullMessage = JSON.stringify({ type: "event", event: publicEvent satisfies TRealtimeEvent });
    let delivered = 0;

    for (const client of room) {
      const membership = client.rooms.get(event.project_id);
      if (!membership) continue;
      if (client.socket.readyState !== WS_OPEN) continue;
      if ((client.socket.bufferedAmount ?? 0) > this.options.maxBufferedBytes) continue;

      let message = fullMessage;
      if (membership.restricted) {
        // Restricted guests only hear about the work items they created.
        const ownIssueIds = publicEvent.issue_ids.filter((issueId) => issueCreators[issueId] === client.userId);
        if (ownIssueIds.length === 0) continue;
        message = JSON.stringify({ type: "event", event: { ...publicEvent, issue_ids: ownIssueIds } });
      }

      try {
        client.socket.send(message);
        delivered += 1;
      } catch {
        // the close handler cleans up
      }
    }
    return delivered;
  }

  roomSize(projectId: string): number {
    return this.rooms.get(projectId)?.size ?? 0;
  }

  stats() {
    let clients = 0;
    for (const set of this.clientsByUser.values()) clients += set.size;
    return { rooms: this.rooms.size, clients };
  }
}

export const realtimeHub = new RealtimeHub();
