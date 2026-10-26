/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// hooks
import { useLabel } from "@/hooks/store/use-label";

type Props = {
  labelIds: string[];
  emptyLabel?: string;
  onClick?: (labelName: string) => void;
};

/** Conjo: page tags as small chips; labels the user cannot see (other projects) are left out. */
export const PageLabelChips = observer(function PageLabelChips(props: Props) {
  const { labelIds, emptyLabel, onClick } = props;
  const { getLabelById } = useLabel();
  const labels = labelIds.map((id) => getLabelById(id)).filter((label) => !!label);

  if (labels.length === 0) return emptyLabel ? <span className="text-11">{emptyLabel}</span> : null;

  return (
    <span className="flex flex-wrap items-center gap-1">
      {labels.map((label) => {
        const content = (
          <>
            <span className="size-1.5 flex-shrink-0 rounded-full" style={{ backgroundColor: label.color }} />
            {label.name}
          </>
        );
        const className =
          "flex items-center gap-1 rounded-full border border-subtle px-2 py-0.5 text-11 text-secondary";
        return onClick ? (
          <button
            key={label.id}
            type="button"
            className={`${className} hover:bg-layer-1-hover`}
            onClick={() => onClick(label.name)}
          >
            {content}
          </button>
        ) : (
          <span key={label.id} className={className}>
            {content}
          </span>
        );
      })}
    </span>
  );
});
