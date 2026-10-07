/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type Redis from "ioredis";
import { logger } from "@plane/logger";
import type { RealtimeHub } from "./hub";
import type { TPublishedEvent } from "./protocol";
import { publishedEventSchema } from "./protocol";

const CHANNEL = "tasks:realtime:events";

/**
 * Delivers published events to the rooms. Alone (no Redis, the default in production) it
 * broadcasts in memory. With Redis it goes through pub/sub so every live instance gets it.
 */
export class RealtimeFanout {
  private publisher: Redis | null = null;
  private subscriber: Redis | null = null;

  constructor(private readonly hub: RealtimeHub) {}

  async initialize(client: Redis | null) {
    if (!client) return;
    try {
      const subscriber = client.duplicate();
      subscriber.on("message", (channel: string, message: string) => {
        if (channel !== CHANNEL) return;
        try {
          const parsed = publishedEventSchema.safeParse(JSON.parse(message));
          if (parsed.success) this.hub.broadcast(parsed.data);
        } catch {
          // ignore malformed messages
        }
      });
      subscriber.on("error", (error: Error) => logger.warn("REALTIME: Redis subscriber error", error));
      await subscriber.subscribe(CHANNEL);
      this.subscriber = subscriber;
      this.publisher = client;
      logger.info("REALTIME: fan-out through Redis pub/sub enabled");
    } catch (error) {
      logger.warn("REALTIME: Redis pub/sub unavailable, broadcasting in memory only", error);
      this.publisher = null;
      this.subscriber = null;
    }
  }

  /** Returns how many local browsers got it (unknown with Redis: the subscription delivers it). */
  async publish(event: TPublishedEvent): Promise<number | null> {
    if (this.publisher && this.publisher.status === "ready") {
      try {
        await this.publisher.publish(CHANNEL, JSON.stringify(event));
        return null;
      } catch (error) {
        logger.warn("REALTIME: Redis publish failed, broadcasting in memory", error);
      }
    }
    return this.hub.broadcast(event);
  }

  async destroy() {
    try {
      await this.subscriber?.quit();
    } catch {
      // ignore
    }
    this.subscriber = null;
    this.publisher = null;
  }
}
