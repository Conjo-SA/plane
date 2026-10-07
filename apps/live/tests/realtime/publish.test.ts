/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { AddressInfo } from "node:net";
import type { Server } from "node:http";
import express from "express";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

const PROJECT = "7c7f9b0e-2f0e-4f3c-9d55-1d0f6f7f2a11";
const ISSUE = "a1a1a1a1-1111-4111-8111-111111111111";

let server: Server;
let url: string;
let hub: typeof import("@/realtime").realtimeHub;
let RealtimeClient: typeof import("@/realtime/hub").RealtimeClient;

beforeAll(async () => {
  vi.stubEnv("API_BASE_URL", "http://api.test:8000");
  vi.stubEnv("LIVE_SERVER_SECRET_KEY", "s3cr3t");
  const { registerController } = await import("@plane/decorators");
  const { RealtimePublishController } = await import("@/controllers/realtime-publish.controller");
  ({ realtimeHub: hub } = await import("@/realtime"));
  ({ RealtimeClient } = await import("@/realtime/hub"));
  const app = express();
  app.use(express.json());
  const router = express.Router();
  registerController(router, RealtimePublishController);
  app.use("/live", router);
  await new Promise<void>((resolve) => {
    server = app.listen(0, () => resolve());
  });
  url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/live/realtime/publish`;
});

afterAll(() => {
  server?.close();
  vi.unstubAllEnvs();
});

const body = { type: "issue.updated", workspace_slug: "conjo", project_id: PROJECT, issue_ids: [ISSUE] };
const post = (headers: Record<string, string>, payload: unknown = body) =>
  fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });

describe("POST /live/realtime/publish", () => {
  it("rejects requests without the right secret", async () => {
    expect((await post({})).status).toBe(401);
    expect((await post({ "live-server-secret-key": "wrong" })).status).toBe(401);
  });

  it("rejects requests that come from a browser", async () => {
    expect((await post({ "live-server-secret-key": "s3cr3t", cookie: "session-id=x" })).status).toBe(403);
    expect((await post({ "live-server-secret-key": "s3cr3t", origin: "https://evil.example" })).status).toBe(403);
  });

  it("rejects invalid events", async () => {
    expect((await post({ "live-server-secret-key": "s3cr3t" }, { ...body, project_id: "x" })).status).toBe(400);
  });

  it("delivers valid events to the project's room", async () => {
    const sent: string[] = [];
    const client = new RealtimeClient({ readyState: 1, send: (data: string) => sent.push(data) }, "u", "c");
    hub.register(client);
    hub.join(client, PROJECT, { workspaceSlug: "conjo", restricted: false });

    const response = await post({ "live-server-secret-key": "s3cr3t" });
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ delivered: 1 });
    expect(JSON.parse(sent[0]).event.issue_ids).toEqual([ISSUE]);
    hub.unregister(client);
  });
});
