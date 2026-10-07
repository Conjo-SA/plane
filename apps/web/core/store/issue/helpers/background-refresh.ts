/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Realtime: called right before a "background" refetch replaces the lists, so the board can
// measure where every card is and animate them to their new place.
const beforeBackgroundApplyListeners = new Set<() => void>();

export const onBeforeBackgroundApply = (listener: () => void) => {
  beforeBackgroundApplyListeners.add(listener);
  return () => {
    beforeBackgroundApplyListeners.delete(listener);
  };
};

export const runBeforeBackgroundApply = () => {
  beforeBackgroundApplyListeners.forEach((listener) => {
    try {
      listener();
    } catch {
      // never break the store update
    }
  });
};
