/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Maximize2, Minus, Plus, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
// plane utils
import { cn } from "@plane/utils";

// Conjo: code blocks in the `mermaid` language render as diagrams (SVG).
import { renderDiagram } from "./mermaid-render";

const isDarkTheme = () => document.documentElement.getAttribute("data-theme")?.startsWith("dark") ?? false;

const getSvgWidth = (svg: string) => {
  const viewBox = /viewBox="[-\d.]+ [-\d.]+ ([\d.]+) [\d.]+"/.exec(svg);
  return viewBox ? Number(viewBox[1]) : undefined;
};

type TDiagramState = { svg: string | null; error: string | null; isLoading: boolean };

export const useMermaidDiagram = (code: string) => {
  const [state, setState] = useState<TDiagramState>({ svg: null, error: null, isLoading: true });
  const [dark, setDark] = useState(() => (typeof document === "undefined" ? false : isDarkTheme()));
  // only diagrams near the screen are drawn (a page can have many)
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (!element || isVisible) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setIsVisible(true);
      },
      { rootMargin: "400px" }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, isVisible]);

  // follow the app theme
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(isDarkTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    if (!code.trim()) {
      setState({ svg: null, error: null, isLoading: false });
      return;
    }
    let cancelled = false;
    // wait for the typing to settle before rendering
    const timeout = setTimeout(() => {
      renderDiagram(code, dark)
        .then((svg) => !cancelled && setState({ svg, error: null, isLoading: false }))
        .catch(
          (error: unknown) =>
            !cancelled &&
            setState({
              svg: null,
              error: error instanceof Error ? error.message : String(error),
              isLoading: false,
            })
        );
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
  }, [code, dark, isVisible]);

  return { ...state, containerRef: setElement };
};

type TMermaidDiagramProps = {
  svg: string | null;
  error: string | null;
  isLoading: boolean;
  containerRef: (element: HTMLDivElement | null) => void;
};

export function MermaidDiagram(props: TMermaidDiagramProps) {
  const { svg, error, isLoading, containerRef } = props;

  if (error)
    return (
      <div
        ref={containerRef}
        className="rounded-lg border border-danger-subtle bg-danger-subtle p-3 text-13 text-danger-primary"
      >
        <p className="font-medium">Não foi possível desenhar o diagrama</p>
        <p className="font-mono mt-1 text-12 whitespace-pre-wrap">{error.split("\n").slice(0, 6).join("\n")}</p>
      </div>
    );
  if (isLoading || !svg)
    return (
      <div
        ref={containerRef}
        className="flex h-24 items-center justify-center rounded-lg bg-layer-3 text-13 text-tertiary"
      >
        {isLoading ? "Desenhando o diagrama…" : "Diagrama vazio"}
      </div>
    );
  return (
    <div
      ref={containerRef}
      className="mermaid-diagram flex justify-center overflow-x-auto rounded-lg bg-layer-1 p-4 [&_svg]:h-auto"
      // the SVG comes from mermaid with securityLevel "strict" and is filtered again by sanitizeSvg
      // oxlint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];

type TMermaidFullscreenProps = {
  svg: string;
  onClose: () => void;
};

export function MermaidFullscreen(props: TMermaidFullscreenProps) {
  const { svg, onClose } = props;
  const [zoomIndex, setZoomIndex] = useState(ZOOM_STEPS.indexOf(1));
  const zoom = ZOOM_STEPS[zoomIndex];
  const naturalWidth = getSvgWidth(svg);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "+" || event.key === "=") setZoomIndex((i) => Math.min(i + 1, ZOOM_STEPS.length - 1));
      if (event.key === "-") setZoomIndex((i) => Math.max(i - 1, 0));
    },
    [onClose]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return createPortal(
    <div className="fixed inset-0 z-[100] flex flex-col bg-surface-1" role="dialog" aria-label="Diagrama em tela cheia">
      <div className="flex items-center justify-end gap-1 border-b border-subtle px-4 py-2">
        <button
          type="button"
          aria-label="Diminuir"
          className="grid size-8 place-items-center rounded-md hover:bg-layer-1-hover"
          onClick={() => setZoomIndex((i) => Math.max(i - 1, 0))}
        >
          <Minus className="size-4" />
        </button>
        <button
          type="button"
          className="min-w-14 rounded-md px-2 py-1 text-13 hover:bg-layer-1-hover"
          onClick={() => setZoomIndex(ZOOM_STEPS.indexOf(1))}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          type="button"
          aria-label="Aumentar"
          className="grid size-8 place-items-center rounded-md hover:bg-layer-1-hover"
          onClick={() => setZoomIndex((i) => Math.min(i + 1, ZOOM_STEPS.length - 1))}
        >
          <Plus className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Fechar"
          className="ml-2 grid size-8 place-items-center rounded-md hover:bg-layer-1-hover"
          onClick={onClose}
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-auto p-6">
        <div
          className="mx-auto [&_svg]:h-auto [&_svg]:w-full [&_svg]:!max-w-none"
          style={{ width: naturalWidth ? `${naturalWidth * zoom}px` : `${zoom * 100}%` }}
          // oxlint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>,
    document.body
  );
}

type TMermaidToolbarProps = {
  showCode: boolean;
  canFullscreen: boolean;
  onToggleCode: () => void;
  onFullscreen: () => void;
};

export function MermaidToolbar(props: TMermaidToolbarProps) {
  const { showCode, canFullscreen, onToggleCode, onFullscreen } = props;
  const buttonClassName =
    "flex h-8 items-center gap-1 rounded-md border border-subtle bg-layer-1 px-2 text-12 text-secondary hover:text-primary";
  return (
    <div contentEditable={false} className="flex items-center gap-1">
      <button type="button" className={buttonClassName} onClick={onToggleCode}>
        {showCode ? "Ver diagrama" : "Ver código"}
      </button>
      {canFullscreen && (
        <button
          type="button"
          aria-label="Tela cheia"
          className={cn(buttonClassName, "w-8 justify-center px-0")}
          onClick={onFullscreen}
        >
          <Maximize2 className="size-3.5" />
        </button>
      )}
    </div>
  );
}
