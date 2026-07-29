/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Editor } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import type { EditorState, Selection } from "@tiptap/pm/state";
// plane imports
import { cn } from "@plane/utils";
// constants
import { CORE_EXTENSIONS } from "@/constants/extension";

type EditorClassNameArgs = {
  noBorder?: boolean;
  borderOnFocus?: boolean;
  containerClassName?: string;
};

export const getEditorClassNames = ({ noBorder, borderOnFocus, containerClassName }: EditorClassNameArgs) =>
  cn(
    "w-full max-w-full focus:border-0 focus:outline-none sm:rounded-lg",
    {
      "border border-subtle-1": !noBorder,
      "border-strong focus:border": borderOnFocus,
    },
    containerClassName
  );

// Helper function to find the parent node of a specific type
export const findParentNodeOfType = (
  selection: Selection,
  typeName: string[]
): {
  node: ProseMirrorNode;
  pos: number;
  depth: number;
} | null => {
  let depth = selection.$anchor.depth;
  while (depth > 0) {
    const node = selection.$anchor.node(depth);
    if (typeName.includes(node.type.name)) {
      return {
        node,
        pos: selection.$anchor.start(depth) - 1,
        depth,
      };
    }
    depth--;
  }
  return null;
};

export const findTableAncestor = (node: Node | null): HTMLTableElement | null => {
  while (node !== null && node.nodeName !== "TABLE") {
    node = node.parentNode;
  }
  return node as HTMLTableElement;
};

/**
 * @description converts a markdown string into editor-compatible HTML using the markdown parser
 * already configured on the editor instance. Headings, lists, tables and fenced code blocks are
 * preserved instead of being flattened into plain text.
 * @param {Editor} editor
 * @param {string} content markdown content
 * @returns {string} HTML string, or the original content when parsing is not possible
 */
export const convertMarkdownToEditorHTML = (editor: Editor, content: string): string => {
  if (!content) return content;
  try {
    const parsedContent: unknown = editor.storage.markdown?.parser?.parse(content, { inline: false });
    return typeof parsedContent === "string" ? parsedContent : content;
  } catch (error) {
    console.error("Failed to parse markdown content:", error);
    return content;
  }
};

export const getTrimmedHTML = (html: string) =>
  html
    .replace(/^(?:<p><\/p>)+/g, "") // Remove from beginning
    .replace(/(?:<p><\/p>)+$/g, ""); // Remove from end

export const isValidHttpUrl = (string: string): { isValid: boolean; url: string } => {
  // List of potentially dangerous protocols to block
  const blockedProtocols = ["javascript:", "data:", "vbscript:", "file:", "about:"];

  // First try with the original string
  try {
    const url = new URL(string);

    // Check for potentially dangerous protocols
    const protocol = url.protocol.toLowerCase();
    if (blockedProtocols.some((p) => protocol === p)) {
      return {
        isValid: false,
        url: string,
      };
    }

    // If URL has any valid protocol, return as is
    if (url.protocol && url.protocol !== "") {
      return {
        isValid: true,
        url: string,
      };
    }
  } catch {
    // Original string wasn't a valid URL - that's okay, we'll try with https
  }

  // Try again with https:// prefix
  try {
    const urlWithHttps = `https://${string}`;
    new URL(urlWithHttps);
    return {
      isValid: true,
      url: urlWithHttps,
    };
  } catch {
    return {
      isValid: false,
      url: string,
    };
  }
};

export const getParagraphCount = (editorState: EditorState | undefined) => {
  if (!editorState) return 0;
  let paragraphCount = 0;
  editorState.doc.descendants((node) => {
    if (node.type.name === CORE_EXTENSIONS.PARAGRAPH && node.content.size > 0) paragraphCount++;
  });
  return paragraphCount;
};
