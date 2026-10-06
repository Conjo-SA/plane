/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

type TUpgradeBadge = {
  className?: string;
  size?: "sm" | "md";
};

// O selo "Pro" (upsell do Plane) foi removido: o componente não renderiza nada.
export function UpgradeBadge(_props: TUpgradeBadge) {
  return null;
}
