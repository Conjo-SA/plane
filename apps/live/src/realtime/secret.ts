/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { createHash, timingSafeEqual } from "node:crypto";

const digest = (value: string) => createHash("sha256").update(value, "utf8").digest();

/**
 * Constant-time check of the shared secret. Both sides are hashed first so neither the
 * content nor the length of the expected secret leaks through timing. An unset (or blank)
 * expected secret never matches.
 */
export const isValidSecret = (provided: unknown, expected: string | undefined): boolean => {
  const expectedSecret = (expected ?? "").trim();
  if (!expectedSecret) return false;
  if (typeof provided !== "string" || provided.length === 0 || provided.length > 1024) return false;
  return timingSafeEqual(digest(provided), digest(expectedSecret));
};
