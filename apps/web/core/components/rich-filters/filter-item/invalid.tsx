/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
import { CircleAlert } from "lucide-react";
// plane imports
import type { TExternalFilter, TFilterProperty } from "@plane/types";
// local imports
import { FilterItemCloseButton } from "./close-button";
import { FilterItemContainer } from "./container";
import { FilterItemProperty } from "./property";
import type { IFilterItemProps } from "./root";

export const InvalidFilterItem = observer(function InvalidFilterItem<
  P extends TFilterProperty,
  E extends TExternalFilter,
>(props: IFilterItemProps<P, E>) {
  const { condition, filter, isDisabled = false, showTransition = true } = props;

  return (
    <FilterItemContainer
      conditionValue={condition.value}
      showTransition={showTransition}
      variant="error"
      tooltipContent="Esta condição de filtro não é mais válida. A propriedade pode ter sido excluída ou seu acesso a ela pode ter mudado."
    >
      {/* Property section */}
      <FilterItemProperty
        conditionId={condition.id}
        icon={CircleAlert}
        label="Filtro inválido"
        filter={filter}
        isDisabled={isDisabled}
      />
      {/* Remove button */}
      {!isDisabled && <FilterItemCloseButton conditionId={condition.id} filter={filter} />}
    </FilterItemContainer>
  );
});
