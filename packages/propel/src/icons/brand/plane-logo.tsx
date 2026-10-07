/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";

import type { ISvgIcons } from "../type";
import { CONJO_WORDMARK_PATH, CONJO_WORDMARK_TRANSFORM } from "./conjo-paths";

// Marca Conjo SA: wordmark "Conjo" vetorizado (substitui o símbolo do Plane).
// Usa currentColor, então segue o tema (preto no claro, branco no escuro).
export function PlaneLogo({ width = "88", height = "32", className, color = "currentColor" }: ISvgIcons) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 2250 825"
      preserveAspectRatio="xMinYMid meet"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="Conjo"
    >
      <path transform={CONJO_WORDMARK_TRANSFORM} d={CONJO_WORDMARK_PATH} fill={color} />
    </svg>
  );
}
