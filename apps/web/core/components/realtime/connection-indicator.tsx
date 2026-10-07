/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// lib
import { realtimeConnection } from "@/lib/realtime/connection";

/** Nothing while connected; a discreet "Reconectando…" when realtime updates are interrupted. */
export const RealtimeConnectionIndicator = observer(function RealtimeConnectionIndicator() {
  if (realtimeConnection.status !== "reconnecting") return null;
  return (
    <span
      role="status"
      aria-live="polite"
      title="As atualizações em tempo real foram interrompidas. Tentando reconectar…"
      className="ml-2 inline-flex shrink-0 items-center gap-1.5 rounded-full border border-subtle bg-layer-1 px-2 py-0.5 text-11 whitespace-nowrap text-tertiary"
    >
      <span className="size-1.5 animate-pulse rounded-full bg-warning-primary motion-reduce:animate-none" />
      Reconectando…
    </span>
  );
});
