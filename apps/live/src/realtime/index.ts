/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { RealtimeFanout } from "./fanout";
import { realtimeHub } from "./hub";

export { realtimeHub } from "./hub";
export const realtimeFanout = new RealtimeFanout(realtimeHub);
