/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";
import { RealtimeClient, RealtimeHub } from "@/realtime/hub";
import { isAllowedOrigin, configuredOrigins } from "@/realtime/origin";
import { parseClientMessage, publishedEventSchema } from "@/realtime/protocol";
import { isValidSecret } from "@/realtime/secret";

const PROJECT = "7c7f9b0e-2f0e-4f3c-9d55-1d0f6f7f2a11";
const OTHER_PROJECT = "1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d";
const ISSUE_A = "a1a1a1a1-1111-4111-8111-111111111111";
const ISSUE_B = "b2b2b2b2-2222-4222-8222-222222222222";
const ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const GUEST = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

class FakeSocket {
  readyState = 1;
  bufferedAmount = 0;
  sent: string[] = [];
  send(data: string) {
    this.sent.push(data);
  }
  get events() {
    return this.sent.map((data) => JSON.parse(data)).filter((message) => message.type === "event");
  }
}

const client = (userId = ALICE) => {
  const socket = new FakeSocket();
  return { socket, client: new RealtimeClient(socket, userId, "session-id=x") };
};

const event = (overrides: Record<string, unknown> = {}) =>
  publishedEventSchema.parse({
    type: "issue.updated",
    workspace_slug: "conjo",
    project_id: PROJECT,
    issue_ids: [ISSUE_A],
    actor_id: ALICE,
    fields: ["state_id"],
    ts: 1,
    ...overrides,
  });

describe("RealtimeHub", () => {
  it("broadcasts only to the project's room and strips internal fields", () => {
    const hub = new RealtimeHub();
    const inRoom = client();
    const elsewhere = client();
    hub.register(inRoom.client);
    hub.register(elsewhere.client);
    hub.join(inRoom.client, PROJECT, { workspaceSlug: "conjo", restricted: false });
    hub.join(elsewhere.client, OTHER_PROJECT, { workspaceSlug: "conjo", restricted: false });

    const delivered = hub.broadcast(event({ issue_creators: { [ISSUE_A]: ALICE } }));

    expect(delivered).toBe(1);
    expect(elsewhere.socket.events).toHaveLength(0);
    expect(inRoom.socket.events).toHaveLength(1);
    expect(inRoom.socket.events[0].event).toEqual({
      type: "issue.updated",
      workspace_slug: "conjo",
      project_id: PROJECT,
      issue_ids: [ISSUE_A],
      actor_id: ALICE,
      fields: ["state_id"],
      ts: 1,
    });
  });

  it("keeps restricted guests to the work items they created", () => {
    const hub = new RealtimeHub();
    const guest = client(GUEST);
    hub.register(guest.client);
    hub.join(guest.client, PROJECT, { workspaceSlug: "conjo", restricted: true });

    hub.broadcast(event({ issue_ids: [ISSUE_A], issue_creators: { [ISSUE_A]: ALICE } }));
    expect(guest.socket.events).toHaveLength(0);

    hub.broadcast(event({ issue_ids: [ISSUE_A, ISSUE_B], issue_creators: { [ISSUE_A]: ALICE, [ISSUE_B]: GUEST } }));
    expect(guest.socket.events).toHaveLength(1);
    expect(guest.socket.events[0].event.issue_ids).toEqual([ISSUE_B]);
    expect(guest.socket.events[0].event.issue_creators).toBeUndefined();
  });

  it("cleans up rooms on leave and unregister", () => {
    const hub = new RealtimeHub();
    const { client: c } = client();
    hub.register(c);
    hub.join(c, PROJECT, { workspaceSlug: "conjo", restricted: false });
    hub.join(c, OTHER_PROJECT, { workspaceSlug: "conjo", restricted: false });
    hub.leave(c, PROJECT);
    expect(hub.roomSize(PROJECT)).toBe(0);
    hub.unregister(c);
    expect(hub.roomSize(OTHER_PROJECT)).toBe(0);
    expect(hub.stats()).toEqual({ rooms: 0, clients: 0 });
  });

  it("caps rooms per socket, joins per minute and sockets per user", () => {
    const hub = new RealtimeHub({
      maxRoomsPerClient: 1,
      maxJoinsPerWindow: 2,
      joinWindowMs: 1000,
      maxClientsPerUser: 1,
    });
    const { client: c } = client();
    expect(hub.register(c)).toBe(true);
    expect(hub.register(client().client)).toBe(false);

    expect(hub.join(c, PROJECT, { workspaceSlug: "conjo", restricted: false })).toBe("joined");
    expect(hub.join(c, OTHER_PROJECT, { workspaceSlug: "conjo", restricted: false })).toBe("too_many_rooms");

    expect(hub.allowJoin(c, 0)).toBe(true);
    expect(hub.allowJoin(c, 10)).toBe(true);
    expect(hub.allowJoin(c, 20)).toBe(false);
    expect(hub.allowJoin(c, 1500)).toBe(true);
  });

  it("skips closed sockets and slow consumers", () => {
    const hub = new RealtimeHub({ maxBufferedBytes: 10 });
    const closed = client();
    const slow = client();
    closed.socket.readyState = 3;
    slow.socket.bufferedAmount = 100;
    for (const c of [closed, slow]) {
      hub.register(c.client);
      hub.join(c.client, PROJECT, { workspaceSlug: "conjo", restricted: false });
    }
    expect(hub.broadcast(event())).toBe(0);
  });
});

describe("protocol", () => {
  it("accepts join/leave/ping and ignores anything else", () => {
    expect(parseClientMessage(JSON.stringify({ type: "join", workspace_slug: "conjo", project_id: PROJECT }))).toEqual({
      type: "join",
      workspace_slug: "conjo",
      project_id: PROJECT,
    });
    expect(parseClientMessage(Buffer.from(JSON.stringify({ type: "ping" })))).toEqual({ type: "ping" });
    expect(parseClientMessage(JSON.stringify({ type: "publish", project_id: PROJECT }))).toBeNull();
    expect(
      parseClientMessage(JSON.stringify({ type: "join", workspace_slug: "../x", project_id: PROJECT }))
    ).toBeNull();
    expect(parseClientMessage(JSON.stringify({ type: "join", workspace_slug: "conjo", project_id: "1" }))).toBeNull();
    expect(parseClientMessage("not json")).toBeNull();
    expect(parseClientMessage(JSON.stringify({ type: "ping", pad: "x".repeat(5000) }))).toBeNull();
  });

  it("rejects published events with data that is not ids", () => {
    expect(publishedEventSchema.safeParse({ ...event(), issue_ids: ["<script>"] }).success).toBe(false);
    expect(publishedEventSchema.safeParse({ ...event(), type: "Issue Updated!" }).success).toBe(false);
    const parsed = publishedEventSchema.parse({ ...event(), name: "Segredo" });
    expect(parsed).not.toHaveProperty("name");
  });
});

describe("secret", () => {
  it("compares in constant time and never accepts an unset secret", () => {
    expect(isValidSecret("s3cr3t", "s3cr3t")).toBe(true);
    expect(isValidSecret("s3cr3", "s3cr3t")).toBe(false);
    expect(isValidSecret(undefined, "s3cr3t")).toBe(false);
    expect(isValidSecret(["s3cr3t"], "s3cr3t")).toBe(false);
    expect(isValidSecret("", "")).toBe(false);
    expect(isValidSecret("anything", "   ")).toBe(false);
  });
});

describe("origin", () => {
  it("accepts the same host and configured origins only", () => {
    const allowed = configuredOrigins({ CORS_ALLOWED_ORIGINS: "http://localhost:3000, ", WEB_BASE_URL: undefined });
    expect(isAllowedOrigin("https://tasks.conjo.com.br", "tasks.conjo.com.br", allowed)).toBe(true);
    expect(isAllowedOrigin("http://localhost:3000", "localhost:3100", allowed)).toBe(true);
    expect(isAllowedOrigin("https://evil.example", "tasks.conjo.com.br", allowed)).toBe(false);
    expect(isAllowedOrigin("null", "tasks.conjo.com.br", allowed)).toBe(false);
    expect(isAllowedOrigin(undefined, "tasks.conjo.com.br", allowed)).toBe(true);
  });
});
