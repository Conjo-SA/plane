/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Conjo: light formatting for estimate notes (same rules as the e-mail, see utils/intake_portal.py).
 * Lines starting with "-", "*" or "•" make a bullet list, "1." or "1)" a numbered list, blank lines
 * separate paragraphs, single line breaks are kept and **text** is bold. Plain text, never HTML.
 */

export type TBudgetNoteBlock = { kind: "p" | "ul" | "ol"; lines: string[] };
export type TBudgetNoteSegment = { text: string; bold: boolean };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export const parseBudgetNote = (text: string | null | undefined): TBudgetNoteBlock[] => {
  const blocks: (TBudgetNoteBlock | null)[] = [];
  for (const raw of (text ?? "").replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const kind = bullet ? "ul" : numbered ? "ol" : "p";
    const content = bullet ? bullet[1] : numbered ? numbered[1] : line;
    if (kind === "p" && !line.trim()) {
      blocks.push(null);
      continue;
    }
    const last = blocks[blocks.length - 1];
    if (last && last.kind === kind) last.lines.push(content);
    else blocks.push({ kind, lines: [content] });
  }
  return blocks.filter((block): block is TBudgetNoteBlock => block !== null);
};

/** Splits a line into plain and **bold** parts. */
export const splitBudgetNoteBold = (line: string): TBudgetNoteSegment[] =>
  line
    .split(/(\*\*.+?\*\*)/g)
    .filter(Boolean)
    .map((part) =>
      part.length > 4 && part.startsWith("**") && part.endsWith("**")
        ? { text: part.slice(2, -2), bold: true }
        : { text: part, bold: false }
    );
