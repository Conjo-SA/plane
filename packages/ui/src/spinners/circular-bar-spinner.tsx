/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";
// components
import { ConjoLoader } from "../conjo-loader";

interface ICircularBarSpinner extends React.SVGAttributes<SVGElement> {
  /** Altura da palavra Conjo; a largura é proporcional (≈ 2,7× a altura). */
  height?: string;
  /** Mantido por compatibilidade; a largura vem da proporção da palavra. */
  width?: string;
  className?: string | undefined;
}

/** Mantém a API antiga, mas desenha o carregando "letra a letra" com o nome Conjo. */
export function CircularBarSpinner({ height = "16px", className = "" }: ICircularBarSpinner) {
  return <ConjoLoader size={height} className={className} />;
}
