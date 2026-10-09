/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ConjoLoader } from "@plane/ui";

// Tela de carregamento: a palavra Conjo "letra a letra", na altura do spinner anterior (24px / 44px no sm+).
export function LogoSpinner() {
  return (
    <div className="flex items-center justify-center">
      <ConjoLoader className="text-primary [--conjo-loader-size:24px] sm:[--conjo-loader-size:44px]" />
    </div>
  );
}
