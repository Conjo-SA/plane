/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Conjo: renders `mermaid` code blocks to SVG. Anyone who can write a page, a comment or an intake request
// can write a diagram that every reader's browser renders, so the input is capped and the output is filtered.

type TMermaid = (typeof import("mermaid"))["default"];

/** Bigger diagrams are refused before mermaid sees them: its pre-processing is quadratic in the text size. */
export const MAX_DIAGRAM_LENGTH = 20_000;
const MAX_EDGES = 300;

// HTML a node label may carry (formatting only): no forms, buttons, popovers, images or links
const LABEL_TAGS = ["b", "i", "em", "strong", "u", "s", "del", "code", "br", "p", "span", "div", "sub", "sup", "small"];
const LABEL_TAGS_HTML = [...LABEL_TAGS, "ul", "ol", "li"];

// What mermaid's own SVG is made of; anything else is dropped
const SVG_ELEMENTS = [
  "svg",
  "g",
  "defs",
  "style",
  "marker",
  "path",
  "rect",
  "circle",
  "ellipse",
  "line",
  "polyline",
  "polygon",
  "text",
  "tspan",
  // journey and timeline wrap their texts in <switch>
  "switch",
  "foreignobject",
  "title",
  "desc",
  "clippath",
  "mask",
  "pattern",
  "lineargradient",
  "radialgradient",
  "stop",
  "filter",
  "fedropshadow",
  "fegaussianblur",
  "feoffset",
  "feblend",
  "feflood",
  "fecomposite",
  "femerge",
  "femergenode",
  "fecolormatrix",
];
const ALLOWED_ELEMENTS = new Set([...SVG_ELEMENTS, ...LABEL_TAGS_HTML]);

// Attributes that run code, navigate, submit, open layers or load something
const BLOCKED_ATTRIBUTE =
  /^(on|formaction$|action$|method$|target$|ping$|srcset$|src$|poster$|background$|popover|command)/i;
const LINK_ATTRIBUTES = new Set(["href", "xlink:href"]);
// Anything in CSS that can make the browser fetch: url() (unless it points inside the SVG), image-set(), image()
const CSS_FETCH = /(url\(\s*(?!["']?#))|image-set\(|(^|[^-])image\(|@import|@font-face/i;

let mermaidPromise: Promise<TMermaid> | null = null;
let renderCount = 0;

// mermaid is big: it is only downloaded when a page has a diagram
const loadMermaid = () => {
  mermaidPromise ??= import("mermaid").then((module) => module.default);
  return mermaidPromise;
};

const cleanStyleAttribute = (element: Element) => {
  const style = (element as HTMLElement | SVGElement).style;
  if (!style) return element.removeAttribute("style");
  // the CSSOM normalizes escapes (u\72l(…) → url(…)) before checking
  for (const property of Array.from(style)) {
    if (CSS_FETCH.test(style.getPropertyValue(property))) style.removeProperty(property);
  }
  if (!style.length) element.removeAttribute("style");
};

const cleanStyleElement = (element: Element) => {
  try {
    const sheet = new CSSStyleSheet();
    // replaceSync drops @import and normalizes escapes
    sheet.replaceSync(element.textContent ?? "");
    element.textContent = Array.from(sheet.cssRules)
      .map((rule) => rule.cssText)
      .filter((cssText) => !CSS_FETCH.test(cssText))
      .join("\n");
  } catch {
    element.remove();
  }
};

/**
 * Defense in depth on top of mermaid's DOMPurify pass: only the elements mermaid draws with, no attribute that
 * runs code, navigates or loads something, and no CSS that fetches.
 */
export const sanitizeSvg = (svg: string) => {
  // the HTML parser (not XML): labels inside <foreignObject> are HTML, e.g. an unclosed <br>
  const template = document.createElement("template");
  template.innerHTML = svg;
  const root = template.content.firstElementChild;
  if (!root || root.nodeName.toLowerCase() !== "svg" || template.content.childElementCount !== 1) return "";
  for (const element of Array.from(root.querySelectorAll("*"))) {
    const name = element.nodeName.toLowerCase();
    if (!ALLOWED_ELEMENTS.has(name)) {
      // links keep their text; anything else goes with its content
      if (name === "a") element.replaceWith(...Array.from(element.childNodes));
      else element.remove();
      continue;
    }
    for (const attribute of Array.from(element.attributes)) {
      const attributeName = attribute.name.toLowerCase();
      // markers and gradients reference ids inside the same SVG
      if (LINK_ATTRIBUTES.has(attributeName)) {
        if (!attribute.value.trim().startsWith("#")) element.removeAttribute(attribute.name);
      } else if (BLOCKED_ATTRIBUTE.test(attributeName)) {
        element.removeAttribute(attribute.name);
      } else if (attributeName !== "style" && (attribute.value.includes("\\") || CSS_FETCH.test(attribute.value))) {
        // presentation attributes such as fill="url(https://…)"; mermaid never writes CSS escapes in them,
        // and an escape (u\72l(…)) would hide a url() from the check
        element.removeAttribute(attribute.name);
      }
    }
    if (element.hasAttribute("style")) cleanStyleAttribute(element);
    if (name === "style") cleanStyleElement(element);
  }
  if (root.hasAttribute("style")) cleanStyleAttribute(root);
  return root.outerHTML;
};

export const renderDiagram = async (code: string, dark: boolean) => {
  if (code.length > MAX_DIAGRAM_LENGTH)
    throw new Error(
      `Diagrama grande demais (${code.length.toLocaleString("pt-BR")} caracteres; o máximo é ${MAX_DIAGRAM_LENGTH.toLocaleString("pt-BR")}).`
    );
  const mermaid = await loadMermaid();
  mermaid.initialize({
    startOnLoad: false,
    // labels are sanitized, click handlers disabled
    securityLevel: "strict",
    suppressErrorRendering: true,
    theme: dark ? "dark" : "default",
    fontFamily: "inherit",
    maxTextSize: MAX_DIAGRAM_LENGTH,
    maxEdges: MAX_EDGES,
    // what a label may contain; it is applied before the label is measured in the DOM
    dompurifyConfig: { ALLOWED_TAGS: LABEL_TAGS_HTML, ALLOWED_ATTR: ["class"], FORBID_TAGS: ["style"] },
    // diagram directives (%%{init: …}%%) cannot change these: mermaid's defaults plus everything that writes CSS
    secure: [
      "secure",
      "securityLevel",
      "startOnLoad",
      "maxTextSize",
      "suppressErrorRendering",
      "maxEdges",
      "dompurifyConfig",
      "themeCSS",
      "themeVariables",
      "fontFamily",
      "altFontFamily",
    ],
  });
  // the flowchart image shape (A@{ img: "https://…" }) is fetched while mermaid lays it out, before any filtering
  const diagram = await mermaid.mermaidAPI.getDiagramFromText(code);
  const vertices = (diagram.db as { getVertices?: () => Map<string, { img?: string }> }).getVertices?.();
  if (vertices && Array.from(vertices.values()).some((vertex) => vertex.img))
    throw new Error("Diagramas não podem ter imagens: o navegador de cada leitor buscaria a imagem fora do Tasks.");
  const id = `conjo-mermaid-${++renderCount}`;
  try {
    const { svg } = await mermaid.render(id, code);
    return sanitizeSvg(svg);
  } finally {
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
  }
};
