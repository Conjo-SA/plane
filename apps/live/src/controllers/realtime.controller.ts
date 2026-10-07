/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Request } from "express";
import type { WebSocket } from "ws";
// plane imports
import { Controller, WebSocket as WSDecorator } from "@plane/decorators";
import { logger } from "@plane/logger";
// env
import { env } from "@/env";
// realtime
import { realtimeHub } from "@/realtime";
import { RealtimeAccessService } from "@/realtime/access";
import { handleRealtimeConnection } from "@/realtime/connection";
import { configuredOrigins } from "@/realtime/origin";

/**
 * Realtime work item updates: browsers join the rooms of the projects they are looking at and
 * get notified (ids only) when something changes there.
 */
@Controller("/realtime")
export class RealtimeController {
  [key: string]: unknown;
  private readonly access = new RealtimeAccessService(env.API_BASE_URL);
  private readonly allowedOrigins = configuredOrigins(process.env);

  @WSDecorator("/")
  handleConnection(ws: WebSocket, req: Request) {
    handleRealtimeConnection(ws, req, {
      hub: realtimeHub,
      access: this.access,
      allowedOrigins: this.allowedOrigins,
    }).catch((error) => {
      logger.error("REALTIME_CONTROLLER: connection error", error);
      try {
        ws.close(1011, "Internal server error");
      } catch {
        // ignore
      }
    });
  }
}
