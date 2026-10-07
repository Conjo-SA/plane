/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { EventEmitter } from "node:events";
import type { IncomingMessage } from "http";
import type { WebSocket } from "ws";
import { describe, expect, it, vi } from "vitest";
import type { RealtimeAccessService, TAccessResult } from "@/realtime/access";
import { CLOSE_FORBIDDEN_ORIGIN, CLOSE_UNAUTHENTICATED, handleRealtimeConnection } from "@/realtime/connection";
import { RealtimeHub } from "@/realtime/hub";
import { publishedEventSchema } from "@/realtime/protocol";

const PROJECT = "7c7f9b0e-2f0e-4f3c-9d55-1d0f6f7f2a11";
const ISSUE = "a1a1a1a1-1111-4111-8111-111111111111";
const ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

class FakeWs extends EventEmitter {
  readyState = 1;
  bufferedAmount = 0;
  sent: Record<string, unknown>[] = [];
  closedWith: number | null = null;
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close(code: number) {
    this.closedWith = code;
    this.readyState = 3;
    this.emit("close");
  }
  terminate() {
    this.close(1006);
  }
  ping() {}
}

const request = (headers: Record<string, string>) => ({ headers }) as unknown as IncomingMessage;

const accessStub = (userId: string | null, project: TAccessResult) =>
  ({
    currentUserId: vi.fn(async () => userId),
    projectAccess: vi.fn(async () => project),
  }) as unknown as RealtimeAccessService;

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const connect = async (headers: Record<string, string>, access: RealtimeAccessService, hub = new RealtimeHub()) => {
  const ws = new FakeWs();
  await handleRealtimeConnection(ws as unknown as WebSocket, request(headers), { hub, access, allowedOrigins: [] });
  return { ws, hub };
};

const HEADERS = { cookie: "session-id=abc", host: "tasks.conjo.com.br", origin: "https://tasks.conjo.com.br" };

describe("realtime connection", () => {
  it("closes without a session cookie", async () => {
    const { ws } = await connect({ host: "tasks.conjo.com.br" }, accessStub(ALICE, { status: "forbidden" }));
    expect(ws.closedWith).toBe(CLOSE_UNAUTHENTICATED);
  });

  it("closes when the session is not valid", async () => {
    const { ws } = await connect(HEADERS, accessStub(null, { status: "forbidden" }));
    expect(ws.closedWith).toBe(CLOSE_UNAUTHENTICATED);
  });

  it("closes connections opened from another site", async () => {
    const { ws } = await connect(
      { ...HEADERS, origin: "https://evil.example" },
      accessStub(ALICE, { status: "forbidden" })
    );
    expect(ws.closedWith).toBe(CLOSE_FORBIDDEN_ORIGIN);
  });

  it("joins a project the API allows and relays its events", async () => {
    const access = accessStub(ALICE, { status: "allowed", userId: ALICE, restricted: false });
    const { ws, hub } = await connect(HEADERS, access);
    expect(ws.sent[0]).toEqual({ type: "ready" });

    ws.emit("message", JSON.stringify({ type: "join", workspace_slug: "conjo", project_id: PROJECT }));
    await flush();
    expect(access.projectAccess).toHaveBeenCalledWith("session-id=abc", "conjo", PROJECT);
    expect(ws.sent).toContainEqual({ type: "joined", project_id: PROJECT });

    hub.broadcast(
      publishedEventSchema.parse({
        type: "issue.updated",
        workspace_slug: "conjo",
        project_id: PROJECT,
        issue_ids: [ISSUE],
      })
    );
    expect(ws.sent.at(-1)).toMatchObject({ type: "event", event: { issue_ids: [ISSUE] } });

    ws.close(1000);
    expect(hub.stats()).toEqual({ rooms: 0, clients: 0 });
  });

  it("refuses projects the user is not a member of", async () => {
    const { ws, hub } = await connect(HEADERS, accessStub(ALICE, { status: "forbidden" }));
    ws.emit("message", JSON.stringify({ type: "join", workspace_slug: "conjo", project_id: PROJECT }));
    await flush();
    expect(ws.sent).toContainEqual({ type: "join_error", project_id: PROJECT, code: "forbidden" });
    expect(hub.roomSize(PROJECT)).toBe(0);
    ws.close(1000);
  });

  it("closes when the session changes to another user", async () => {
    const other = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    const { ws } = await connect(HEADERS, accessStub(ALICE, { status: "allowed", userId: other, restricted: false }));
    ws.emit("message", JSON.stringify({ type: "join", workspace_slug: "conjo", project_id: PROJECT }));
    await flush();
    expect(ws.closedWith).toBe(CLOSE_UNAUTHENTICATED);
  });

  it("answers pings and ignores unknown messages", async () => {
    const { ws } = await connect(HEADERS, accessStub(ALICE, { status: "forbidden" }));
    ws.emit("message", JSON.stringify({ type: "ping" }));
    ws.emit("message", JSON.stringify({ type: "publish", project_id: PROJECT }));
    expect(ws.sent.at(-1)).toEqual({ type: "pong" });
    expect(ws.closedWith).toBeNull();
    ws.close(1000);
  });
});
