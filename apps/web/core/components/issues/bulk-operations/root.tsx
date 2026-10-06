/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import type { TSelectionHelper } from "@/hooks/use-multiple-select";

type Props = {
  className?: string;
  selectionHelpers: TSelectionHelper;
};

// O banner de upgrade (upsell do Plane One) foi removido; não há operações em massa nesta edição.
export const IssueBulkOperationsRoot = observer(function IssueBulkOperationsRoot(_props: Props) {
  return null;
});
