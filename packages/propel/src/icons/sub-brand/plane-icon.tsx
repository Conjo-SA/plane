/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";

import { CONJO_MARK_PATH, CONJO_MARK_TRANSFORM } from "../brand/conjo-paths";
import { IconWrapper } from "../icon-wrapper";
import type { ISvgIcons } from "../type";

// Marca Conjo SA: símbolo "C" (substitui o ícone do Plane).
export function PlaneNewIcon({ color = "currentColor", ...rest }: ISvgIcons) {
  return (
    <IconWrapper color={color} viewBox="0 0 726 726" {...rest}>
      <g transform="translate(94.5 0)">
        <path transform={CONJO_MARK_TRANSFORM} d={CONJO_MARK_PATH} fill={color} />
      </g>
    </IconWrapper>
  );
}
