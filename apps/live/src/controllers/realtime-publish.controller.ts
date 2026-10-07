/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Request, Response } from "express";
// plane imports
import { Controller, Post } from "@plane/decorators";
import { logger } from "@plane/logger";
// env
import { env } from "@/env";
// realtime
import { realtimeFanout } from "@/realtime";
import { publishedEventSchema } from "@/realtime/protocol";
import { isValidSecret } from "@/realtime/secret";

/**
 * Internal endpoint the API and its workers call when work items change. Reachable through the
 * public proxy path too, so it is protected by the shared secret (constant-time check) and refuses
 * anything that looks like it comes from a browser (cookies or an Origin header).
 */
@Controller("/realtime")
export class RealtimePublishController {
  @Post("/publish")
  async publish(req: Request, res: Response) {
    if (req.headers.cookie || req.headers.origin) {
      res.status(403).json({ error: "Forbidden" });
      return;
    }
    if (!isValidSecret(req.headers["live-server-secret-key"], env.LIVE_SERVER_SECRET_KEY)) {
      logger.warn(`REALTIME: rejected publish without a valid secret from ${req.ip}`);
      res.status(401).json({ error: "Unauthorized" });
      return;
    }
    const parsed = publishedEventSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "Invalid event" });
      return;
    }
    try {
      const delivered = await realtimeFanout.publish(parsed.data);
      res.status(202).json({ delivered });
    } catch (error) {
      logger.error("REALTIME: publish failed", error);
      res.status(500).json({ error: "Publish failed" });
    }
  }
}
