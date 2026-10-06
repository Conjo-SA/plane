/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";

import type { ISvgIcons } from "../type";

// Marca Conjo: wordmark em texto "Tasks" (substitui o wordmark do Plane).
export function PlaneWordmark({ width = "138", height = "44", className, color = "currentColor" }: ISvgIcons) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 100 32"
      preserveAspectRatio="xMinYMid meet"
      fill={color}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="Tasks"
    >
      <text
        x="0"
        y="25"
        fill={color}
        fontFamily="inherit"
        fontSize="30"
        fontWeight="700"
        letterSpacing="-0.5"
        textLength="98"
        lengthAdjust="spacingAndGlyphs"
      >
        Tasks
      </text>
    </svg>
  );
}
