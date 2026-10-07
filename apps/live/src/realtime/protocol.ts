/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { z } from "zod";

/** Max size of a message a browser may send (join/leave/ping are tiny). */
export const MAX_CLIENT_MESSAGE_BYTES = 4096;

const UUID = z.string().uuid();
const SLUG = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[A-Za-z0-9_-]+$/);
const FIELD = z
  .string()
  .max(64)
  .regex(/^[A-Za-z0-9_.-]+$/);

/**
 * What the API publishes. Only ids, field names and the actor: never titles or descriptions.
 * `issue_creators` is internal (used to keep restricted guests to their own work items) and
 * is stripped before anything reaches a browser.
 */
export const publishedEventSchema = z
  .object({
    type: z
      .string()
      .min(1)
      .max(64)
      .regex(/^[a-z_]+(\.[a-z_]+)*$/),
    workspace_slug: z.union([SLUG, z.literal("")]),
    project_id: UUID,
    issue_ids: z.array(UUID).max(500).default([]),
    actor_id: UUID.nullable().optional(),
    fields: z.array(FIELD).max(50).default([]),
    ts: z.number().int().nonnegative().optional(),
    issue_creators: z.record(UUID, UUID).optional(),
  })
  .strip();

export type TPublishedEvent = z.infer<typeof publishedEventSchema>;

/** What a browser receives. */
export type TRealtimeEvent = Omit<TPublishedEvent, "issue_creators">;

export const clientMessageSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("join"), workspace_slug: SLUG, project_id: UUID }),
  z.object({ type: z.literal("leave"), project_id: UUID }),
  z.object({ type: z.literal("ping") }),
]);

export type TClientMessage = z.infer<typeof clientMessageSchema>;

/**
 * Parses a raw WebSocket message from a browser. Returns null for anything oversized,
 * malformed or of an unknown type (which is simply ignored).
 */
export const parseClientMessage = (raw: unknown): TClientMessage | null => {
  let text: string;
  if (typeof raw === "string") text = raw;
  else if (Buffer.isBuffer(raw)) text = raw.toString("utf8");
  else if (Array.isArray(raw)) text = Buffer.concat(raw as Buffer[]).toString("utf8");
  else if (raw instanceof ArrayBuffer) text = Buffer.from(raw).toString("utf8");
  else return null;
  if (Buffer.byteLength(text, "utf8") > MAX_CLIENT_MESSAGE_BYTES) return null;
  try {
    const result = clientMessageSchema.safeParse(JSON.parse(text));
    return result.success ? result.data : null;
  } catch {
    return null;
  }
};
