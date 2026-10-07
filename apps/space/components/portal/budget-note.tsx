/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { cn, parseBudgetNote, splitBudgetNoteBold } from "@plane/utils";

type Props = { text: string; className?: string };

/** Estimate note with paragraphs, lists and **bold** (plain text, never HTML). */
export function BudgetNote(props: Props) {
  const { text, className } = props;
  const blocks = parseBudgetNote(text);
  if (blocks.length === 0) return null;

  const inline = (line: string) =>
    splitBudgetNoteBold(line).map((segment, index) =>
      segment.bold ? (
        // oxlint-disable-next-line react/no-array-index-key -- segments of one line have no identity
        <strong key={index} className="font-semibold text-primary">
          {segment.text}
        </strong>
      ) : (
        // oxlint-disable-next-line react/no-array-index-key -- segments of one line have no identity
        <span key={index}>{segment.text}</span>
      )
    );

  return (
    <div className={cn("space-y-1.5 text-12 leading-relaxed text-secondary", className)}>
      {blocks.map((block, blockIndex) => {
        // oxlint-disable-next-line react/no-array-index-key -- blocks are derived from the text, in order
        const key = `${block.kind}-${blockIndex}`;
        if (block.kind === "p")
          return (
            <p key={key}>
              {block.lines.map((line, lineIndex) => (
                // oxlint-disable-next-line react/no-array-index-key -- lines of a paragraph, in order
                <span key={lineIndex}>
                  {lineIndex > 0 && <br />}
                  {inline(line)}
                </span>
              ))}
            </p>
          );
        const List = block.kind === "ul" ? "ul" : "ol";
        return (
          <List key={key} className={cn("space-y-0.5 pl-5", block.kind === "ul" ? "list-disc" : "list-decimal")}>
            {block.lines.map((line, lineIndex) => (
              // oxlint-disable-next-line react/no-array-index-key -- list items, in order
              <li key={lineIndex}>{inline(line)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
