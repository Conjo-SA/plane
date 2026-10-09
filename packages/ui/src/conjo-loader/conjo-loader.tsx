/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";
// helpers
import { cn } from "../utils";

/** Proporção da palavra "Conjo" no design (caixa de 240×88). */
export const CONJO_LOADER_ASPECT_RATIO = 240 / 88;

export interface IConjoLoader extends React.HTMLAttributes<HTMLSpanElement> {
  /**
   * Altura da palavra (número em px ou qualquer medida CSS); a largura é proporcional (≈ 2,7×).
   * Sem `size`, vale `--conjo-loader-size` (20px por padrão), que também pode vir de uma classe,
   * ex.: `[--conjo-loader-size:24px] sm:[--conjo-loader-size:44px]`.
   */
  size?: number | string;
}

/**
 * Carregando "letra a letra" com o nome Conjo, no lugar dos spinners. As letras são as peças da logo
 * usadas como máscara na cor do texto (`currentColor`), sobem uma a uma e o pingo do "j" cai por
 * último; fica parado com "reduzir movimento". Estilos em `@plane/ui/styles/conjo-loader.css`.
 */
export function ConjoLoader({
  size,
  className,
  style,
  role = "status",
  "aria-label": ariaLabel = "Carregando",
  ...props
}: IConjoLoader) {
  const sizeStyle =
    size === undefined
      ? undefined
      : ({ "--conjo-loader-size": typeof size === "number" ? `${size}px` : size } as React.CSSProperties);

  return (
    <span
      role={role}
      aria-label={ariaLabel}
      className={cn("conjo-loader", className)}
      style={{ ...sizeStyle, ...style }}
      {...props}
    >
      <span className="conjo-loader__piece conjo-loader__c" aria-hidden="true" />
      <span className="conjo-loader__piece conjo-loader__o1" aria-hidden="true" />
      <span className="conjo-loader__piece conjo-loader__nj" aria-hidden="true" />
      <span className="conjo-loader__piece conjo-loader__o2" aria-hidden="true" />
      <span className="conjo-loader__piece conjo-loader__dot" aria-hidden="true" />
    </span>
  );
}
