/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";

import type { ISvgIcons } from "../type";
import { CONJO_WORDMARK_PATH, CONJO_WORDMARK_TRANSFORM } from "./conjo-paths";

// Marca Conjo SA: wordmark "Conjo" + nome do produto "Tasks" (substitui o
// lockup do Plane). Usa currentColor, então segue o tema da aplicação.
export function PlaneLockup({ width = "166", height = "33", className, color = "currentColor" }: ISvgIcons) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 4150 825"
      preserveAspectRatio="xMinYMid meet"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="Conjo Tasks"
    >
      <path transform={CONJO_WORDMARK_TRANSFORM} d={CONJO_WORDMARK_PATH} fill={color} />
      <rect x="2440" y="285" width="28" height="480" fill={color} opacity="0.35" />
      <text
        x="2640"
        y="765"
        fill={color}
        fontFamily="inherit"
        fontSize="580"
        fontWeight="500"
        textLength="1460"
        lengthAdjust="spacingAndGlyphs"
      >
        Tasks
      </text>
    </svg>
  );
}
