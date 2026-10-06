/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Spinner } from "@plane/ui";

// Spinner genérico no lugar do GIF animado com o logo do Plane.
export function LogoSpinner() {
  return (
    <div className="flex items-center justify-center">
      <Spinner className="h-6 w-6 sm:h-11 sm:w-11" />
    </div>
  );
}
