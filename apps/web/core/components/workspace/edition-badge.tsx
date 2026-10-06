/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import packageJson from "package.json";

// Antes abria o modal de upgrade para os planos pagos do Plane; agora só mostra a versão.
export function WorkspaceEditionBadge() {
  return <span className="px-2 text-11 text-tertiary">Tasks v{packageJson.version}</span>;
}
