/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CopyIcon } from "@plane/propel/icons";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import type { Editor } from "@tiptap/react";
import { NodeViewContent, NodeViewWrapper } from "@tiptap/react";
import ts from "highlight.js/lib/languages/typescript";
import { common, createLowlight } from "lowlight";
import { CheckIcon } from "lucide-react";
import { useEffect, useState } from "react";
// ui
import { Tooltip } from "@plane/propel/tooltip";
// plane utils
import { cn } from "@plane/utils";
// local imports
import { MermaidDiagram, MermaidFullscreen, MermaidToolbar, useMermaidDiagram } from "./mermaid-diagram";
// types
import type { TCodeBlockAttributes } from "./types";
import { ECodeBlockAttributeNames } from "./types";

// we just have ts support for now
const lowlight = createLowlight(common);
lowlight.register("ts", ts);

type Props = {
  node: ProseMirrorNode;
  editor: Editor;
  getPos: () => number | undefined;
};

// Conjo: a `mermaid` code block shows the diagram; the code stays in the document and shows up to be edited
function MermaidCodeBlock({ node, editor, getPos }: Props) {
  const attrs = node.attrs as TCodeBlockAttributes;
  const code = node.textContent;
  const [showCode, setShowCode] = useState(() => editor.isEditable && !code.trim());
  const [isFullscreen, setIsFullscreen] = useState(false);
  const diagram = useMermaidDiagram(code);

  // the cursor entering the block (arrow keys, search) shows the code, so nobody types into a hidden block
  useEffect(() => {
    const handleSelection = () => {
      const pos = getPos();
      if (!editor.isEditable || pos === undefined) return;
      const { from, to } = editor.state.selection;
      if (from > pos && to < pos + node.nodeSize) setShowCode(true);
    };
    editor.on("selectionUpdate", handleSelection);
    return () => {
      editor.off("selectionUpdate", handleSelection);
    };
  }, [editor, getPos, node.nodeSize]);

  return (
    <NodeViewWrapper key={attrs[ECodeBlockAttributeNames.ID]} className="code-block mermaid-code-block my-2">
      <div contentEditable={false} className="mb-1 flex items-center justify-between select-none">
        <span className="font-mono rounded-sm px-1.5 py-0.5 text-caption-sm-regular text-tertiary uppercase">
          mermaid
        </span>
        <MermaidToolbar
          showCode={showCode}
          canFullscreen={!!diagram.svg}
          onToggleCode={() => setShowCode((value) => !value)}
          onFullscreen={() => setIsFullscreen(true)}
        />
      </div>
      {!showCode && (
        <div contentEditable={false} className="mermaid-breakout">
          <MermaidDiagram {...diagram} />
        </div>
      )}
      <pre className={cn("rounded-lg bg-layer-3 p-4 text-primary", { hidden: !showCode })}>
        <NodeViewContent as="code" className="whitespace-pre-wrap" />
      </pre>
      {isFullscreen && diagram.svg && <MermaidFullscreen svg={diagram.svg} onClose={() => setIsFullscreen(false)} />}
    </NodeViewWrapper>
  );
}

export function CodeBlockComponent(props: Props) {
  if ((props.node.attrs as TCodeBlockAttributes)[ECodeBlockAttributeNames.LANGUAGE] === "mermaid")
    return <MermaidCodeBlock {...props} />;
  return <PlainCodeBlock node={props.node} />;
}

function PlainCodeBlock({ node }: Pick<Props, "node">) {
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
          className="font-mono absolute top-2 left-3 z-10 rounded-sm px-1.5 py-0.5 text-caption-sm-regular text-tertiary uppercase select-none"
        >
          {attrs[ECodeBlockAttributeNames.LANGUAGE]}
        </span>
      )}
      <Tooltip tooltipContent="Copiar código">
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
