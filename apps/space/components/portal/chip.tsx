/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

type Props = {
  label: string;
  /** Color of the dot; the chip itself stays neutral, like labels on the Tasks board. */
  color?: string | null;
  title?: string;
};

/** Small chip in the Tasks style (square corners, hairline border, colored dot). */
export function PortalChip(props: Props) {
  const { label, color, title } = props;
  return (
    <span
      title={title}
      className="inline-flex h-5 w-fit shrink-0 items-center gap-1.5 rounded-sm border-[0.5px] border-strong bg-surface-1 px-2 text-11 whitespace-nowrap text-secondary"
    >
      {color && <span aria-hidden className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />}
      {label}
    </span>
  );
}
