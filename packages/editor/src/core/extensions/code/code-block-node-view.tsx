/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CopyIcon } from "@plane/propel/icons";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { NodeViewContent, NodeViewWrapper } from "@tiptap/react";
import ts from "highlight.js/lib/languages/typescript";
import { common, createLowlight } from "lowlight";
import { CheckIcon } from "lucide-react";
import { useState } from "react";
// ui
import { Tooltip } from "@plane/propel/tooltip";
// plane utils
import { cn } from "@plane/utils";
// types
import type { TCodeBlockAttributes } from "./types";
import { ECodeBlockAttributeNames } from "./types";

// we just have ts support for now
const lowlight = createLowlight(common);
lowlight.register("ts", ts);

type Props = {
  node: ProseMirrorNode;
};

export function CodeBlockComponent({ node }: Props) {
  const [copied, setCopied] = useState(false);
  // derived values
  const attrs = node.attrs as TCodeBlockAttributes;

  const copyToClipboard = async (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
    try {
      await navigator.clipboard.writeText(node.textContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 1000);
    } catch {
      setCopied(false);
    }
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <NodeViewWrapper key={attrs[ECodeBlockAttributeNames.ID]} className="code-block group/code relative">
      {attrs[ECodeBlockAttributeNames.LANGUAGE] && (
        <span
          contentEditable={false}
          className="absolute top-2 left-3 z-10 rounded-sm px-1.5 py-0.5 font-mono text-caption-sm-regular text-tertiary uppercase select-none"
        >
          {attrs[ECodeBlockAttributeNames.LANGUAGE]}
        </span>
      )}
      <Tooltip tooltipContent="Copy code">
        <button
          type="button"
          className={cn(
            "group/button absolute top-2 right-2 z-10 hidden size-8 items-center justify-center rounded-md border border-subtle bg-layer-1 backdrop-blur-sm transition duration-150 ease-in-out group-hover/code:flex",
            {
              "bg-success-subtle hover:bg-success-subtle-1 active:bg-success-subtle-1": copied,
            }
          )}
          onClick={(e) => void copyToClipboard(e)}
        >
          {copied ? (
            <CheckIcon className="h-3 w-3 text-success-primary" strokeWidth={3} />
          ) : (
            <CopyIcon className="h-3 w-3 text-tertiary group-hover/button:text-primary" />
          )}
        </button>
      </Tooltip>

      <pre
        className={cn("my-2 rounded-lg bg-layer-3 p-4 text-primary", {
          "pt-8": !!attrs[ECodeBlockAttributeNames.LANGUAGE],
        })}
      >
        <NodeViewContent as="code" className="whitespace-pre-wrap" />
      </pre>
    </NodeViewWrapper>
  );
}
