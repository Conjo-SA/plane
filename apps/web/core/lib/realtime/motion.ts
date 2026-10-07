/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Movement animations for work items changed by someone else (FLIP: measure, change, invert, play).
 *
 * Work items on screen are found by `data-rt-issue` (board cards and list rows, with `data-rt-key`
 * unique per rendered instance, e.g. the card in a column) or by their `issue-<uuid>` element id
 * (spreadsheet rows, calendar blocks, sub-items, gantt). Before a remote change is applied to the stores
 * the layout is captured; after React renders, every card that moved glides from its old place to
 * the new one, new cards fade in and changed cards get a short highlight. A card that changed column
 * would be clipped by the column's scroll container (it seemed to travel behind the columns), so it
 * flies as a copy in a layer above the board while the real card stays hidden until it lands. Only Web Animations are
 * used (no classes or inline styles), so React re-renders never fight the animation. Nothing is
 * animated while the user drags, and movement respects `prefers-reduced-motion`.
 */

const SELECTOR = '[data-rt-issue], [id^="issue-"]';
const ID_PATTERN = /^issue-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;
const MOVE_DURATION_MS = 320;
const FLY_DURATION_MS = 480;
const ENTER_DURATION_MS = 260;
const LEAVE_DURATION_MS = 200;
const HIGHLIGHT_DURATION_MS = 1300;
const BADGE_DURATION_MS = 1800;
const MAX_BADGES = 3;
const EASING = "cubic-bezier(0.2, 0, 0, 1)";

type TRect = { left: number; top: number; width: number; height: number };
export type TLayoutSnapshot = {
  byKey: Map<string, TRect>;
  byIssue: Map<string, TRect>;
};

let dragging = false;
if (typeof window !== "undefined") {
  window.addEventListener("dragstart", () => (dragging = true), true);
  window.addEventListener("dragend", () => (dragging = false), true);
  window.addEventListener("drop", () => (dragging = false), true);
}

/** The user is dragging a card: remote changes wait, nothing animates. */
export const isDragInProgress = () => dragging;

const canAnimate = () =>
  typeof document !== "undefined" && typeof Element !== "undefined" && "animate" in Element.prototype;

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Spreadsheet rows carry the id on their first cell: animate the whole row. */
const targetOf = (element: HTMLElement): HTMLElement =>
  element.tagName === "TD" && element.parentElement ? element.parentElement : element;

const issueIdOf = (element: HTMLElement): string | undefined =>
  element.dataset.rtIssue || ID_PATTERN.exec(element.id)?.[1];

type TItem = { element: HTMLElement; target: HTMLElement; issueId: string; key: string };

/** Every rendered work item, once (an element inside another one of the same work item is skipped). */
const items = (): TItem[] => {
  if (typeof document === "undefined") return [];
  const result: TItem[] = [];
  const occurrences = new Map<string, number>();
  for (const element of Array.from(document.querySelectorAll<HTMLElement>(SELECTOR))) {
    const issueId = issueIdOf(element);
    if (!issueId) continue;
    const ancestor = element.parentElement?.closest<HTMLElement>(SELECTOR);
    if (ancestor && issueIdOf(ancestor) === issueId) continue;
    const occurrence = occurrences.get(issueId) ?? 0;
    occurrences.set(issueId, occurrence + 1);
    const key = element.dataset.rtKey ?? `${issueId}#${occurrence}`;
    result.push({ element, target: targetOf(element), issueId, key });
  }
  return result;
};

const isNearViewport = (rect: TRect) =>
  rect.top + rect.height > -200 &&
  rect.top < window.innerHeight + 200 &&
  rect.left + rect.width > -200 &&
  rect.left < window.innerWidth + 200;

export const captureLayout = (): TLayoutSnapshot => {
  const snapshot: TLayoutSnapshot = { byKey: new Map(), byIssue: new Map() };
  if (!canAnimate()) return snapshot;
  for (const { target, issueId, key } of items()) {
    const rect = target.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const box = { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
    snapshot.byKey.set(key, box);
    if (!snapshot.byIssue.has(issueId)) snapshot.byIssue.set(issueId, box);
  }
  return snapshot;
};

const readAccentColor = () => {
  const value = getComputedStyle(document.documentElement).getPropertyValue("--border-color-accent-strong").trim();
  return value || "rgb(63, 118, 255)";
};

const highlight = (element: HTMLElement, accent: string) => {
  const surface = element.querySelector<HTMLElement>("[data-rt-surface]") ?? element;
  if (surface.tagName === "TR") {
    // table rows do not paint box-shadows reliably: tint the cells instead
    surface.querySelectorAll<HTMLElement>(":scope > td").forEach((cell) => {
      cell.animate(
        [
          { boxShadow: `inset 0 0 0 9999px color-mix(in srgb, ${accent} 14%, transparent)` },
          { boxShadow: "inset 0 0 0 9999px transparent" },
        ],
        { duration: HIGHLIGHT_DURATION_MS, easing: "ease-out" }
      );
    });
    return;
  }
  surface.animate(
    [
      { boxShadow: `0 0 0 2px ${accent}, 0 0 14px 2px color-mix(in srgb, ${accent} 40%, transparent)` },
      { boxShadow: `0 0 0 2px ${accent}, 0 0 14px 2px color-mix(in srgb, ${accent} 40%, transparent)`, offset: 0.35 },
      { boxShadow: "0 0 0 2px transparent, 0 0 0 0 transparent" },
    ],
    { duration: HIGHLIGHT_DURATION_MS, easing: "ease-out" }
  );
};

/** Small "Atualizado por <nome>" label next to the card, outside React's tree. */
const showBadge = (element: HTMLElement, text: string, accent: string) => {
  const rect = targetOf(element).getBoundingClientRect();
  if (!isNearViewport(rect) || rect.top < 0 || rect.top > window.innerHeight) return;
  const badge = document.createElement("div");
  badge.textContent = text;
  badge.setAttribute("role", "status");
  Object.assign(badge.style, {
    position: "fixed",
    top: `${Math.max(4, rect.top - 10)}px`,
    left: `${Math.max(4, Math.min(window.innerWidth - 220, rect.left + rect.width - 8))}px`,
    transform: "translateX(-100%)",
    zIndex: "40",
    pointerEvents: "none",
    padding: "2px 8px",
    borderRadius: "9999px",
    fontSize: "11px",
    lineHeight: "16px",
    whiteSpace: "nowrap",
    maxWidth: "200px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    color: "#fff",
    background: accent,
    boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
  } satisfies Partial<CSSStyleDeclaration>);
  document.body.appendChild(badge);
  const animation = badge.animate(
    [
      { opacity: 0, offset: 0 },
      { opacity: 1, offset: 0.1 },
      { opacity: 1, offset: 0.8 },
      { opacity: 0, offset: 1 },
    ],
    { duration: BADGE_DURATION_MS, easing: "ease-out" }
  );
  const remove = () => badge.remove();
  animation.onfinish = remove;
  setTimeout(remove, BADGE_DURATION_MS + 200);
};

/** The box that clips the element: its nearest ancestor that does not let content overflow. */
const clipRectOf = (element: HTMLElement): DOMRect | null => {
  for (let node = element.parentElement; node && node !== document.body; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (/(auto|scroll|hidden|clip)/.test(style.overflow + style.overflowX + style.overflowY))
      return node.getBoundingClientRect();
  }
  return null;
};

const isInside = (box: TRect, clip: DOMRect) =>
  box.left >= clip.left - 1 &&
  box.top >= clip.top - 1 &&
  box.left + box.width <= clip.right + 1 &&
  box.top + box.height <= clip.bottom + 1;

/** Flies a copy of the card above everything, from its old place to the new one. */
const flyAcross = (target: HTMLElement, from: TRect, to: DOMRect) => {
  const ghost = target.cloneNode(true) as HTMLElement;
  // the copy must never be taken for the card itself
  ghost.removeAttribute("id");
  ghost.removeAttribute("data-rt-issue");
  ghost.removeAttribute("data-rt-key");
  ghost.querySelectorAll("[id], [data-rt-issue]").forEach((node) => {
    node.removeAttribute("id");
    node.removeAttribute("data-rt-issue");
  });
  ghost.setAttribute("aria-hidden", "true");
  Object.assign(ghost.style, {
    position: "fixed",
    left: `${to.left}px`,
    top: `${to.top}px`,
    width: `${to.width}px`,
    height: `${to.height}px`,
    margin: "0",
    boxSizing: "border-box",
    zIndex: "50",
    pointerEvents: "none",
  } satisfies Partial<CSSStyleDeclaration>);
  document.body.appendChild(ghost);

  const dx = from.left - to.left;
  const dy = from.top - to.top;
  const flight = ghost.animate(
    [
      { transform: `translate(${dx}px, ${dy}px) scale(1)`, boxShadow: "0 0 0 0 rgba(0,0,0,0)" },
      {
        transform: `translate(${dx * 0.5}px, ${dy * 0.5 - 12}px) scale(1.03)`,
        boxShadow: "0 12px 28px rgba(0,0,0,0.18)",
        offset: 0.5,
      },
      { transform: "translate(0, 0) scale(1)", boxShadow: "0 0 0 0 rgba(0,0,0,0)" },
    ],
    { duration: FLY_DURATION_MS, easing: EASING }
  );
  // the real card waits, invisible, in its new place
  const hidden = target.animate([{ opacity: 0 }, { opacity: 0 }], { duration: FLY_DURATION_MS });
  const land = () => {
    ghost.remove();
    hidden.cancel();
  };
  flight.addEventListener("finish", land);
  flight.addEventListener("cancel", land);
  setTimeout(land, FLY_DURATION_MS + 200);
};

export type TPlayOptions = {
  /** Work items changed by this update (they may have changed column). */
  changedIssueIds: Set<string>;
  /** Changed by someone else: highlight them. */
  highlightIssueIds?: Set<string>;
  /** Fade in cards that were not on screen before (new work items). */
  animateNewCards?: boolean;
  /** "Atualizado por Fulano", shown for a few changed cards. */
  badgeText?: string;
};

/** Plays the animations after React has rendered the new layout. */
export const playLayoutChanges = (before: TLayoutSnapshot, options: TPlayOptions) => {
  if (!canAnimate() || isDragInProgress()) return;
  // React commits MobX-triggered renders before the next frame; measure then, before paint.
  requestAnimationFrame(() => {
    if (isDragInProgress()) return;
    const reduceMotion = prefersReducedMotion();
    const accent = readAccentColor();
    let badges = 0;
    // nested rows (sub-items inside an expanded list row) move with their parent
    const moved = new Set<HTMLElement>();

    for (const { target, issueId, key } of items()) {
      const rect = target.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;
      if (!isNearViewport(rect)) continue;
      const ancestor = target.parentElement?.closest<HTMLElement>(SELECTOR);
      const movesWithAncestor = !!ancestor && moved.has(targetOf(ancestor));

      let flew = false;
      let previous = before.byKey.get(key);
      if (!previous && options.changedIssueIds.has(issueId)) previous = before.byIssue.get(issueId);

      if (previous) {
        const dx = previous.left - rect.left;
        const dy = previous.top - rect.top;
        if (!reduceMotion && !movesWithAncestor && (Math.abs(dx) > 1 || Math.abs(dy) > 1)) {
          moved.add(target);
          const clip = clipRectOf(target);
          if (clip && !isInside(previous, clip)) {
            flyAcross(target, previous, rect);
            flew = true;
          } else {
            target.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }], {
              duration: MOVE_DURATION_MS,
              easing: EASING,
            });
          }
        }
      } else if (options.animateNewCards && !before.byIssue.has(issueId) && !reduceMotion && !movesWithAncestor) {
        target.animate(
          [
            { opacity: 0, transform: "scale(0.96)" },
            { opacity: 1, transform: "scale(1)" },
          ],
          { duration: ENTER_DURATION_MS, easing: EASING }
        );
      }

      if (options.highlightIssueIds?.has(issueId)) {
        const withBadge = !!options.badgeText && badges < MAX_BADGES && options.highlightIssueIds.size <= MAX_BADGES;
        if (withBadge) badges += 1;
        const mark = () => {
          highlight(target, accent);
          if (withBadge && options.badgeText) showBadge(target, options.badgeText, accent);
        };
        // a card in flight is marked once it lands
        if (flew) setTimeout(mark, FLY_DURATION_MS);
        else mark();
      }
    }
  });
};

/** Fades cards out before they are removed from the stores. */
export const animateRemoval = async (issueIds: Set<string>): Promise<void> => {
  if (!canAnimate() || issueIds.size === 0 || isDragInProgress() || prefersReducedMotion()) return;
  const animations = items()
    .filter((item) => issueIds.has(item.issueId))
    .map((item) => item.target)
    .filter((target) => isNearViewport(target.getBoundingClientRect()))
    .map((target) =>
      target.animate(
        [
          { opacity: 1, transform: "scale(1)" },
          { opacity: 0, transform: "scale(0.96)" },
        ],
        { duration: LEAVE_DURATION_MS, easing: "ease-in", fill: "forwards" }
      )
    );
  if (animations.length === 0) return;
  await Promise.race([
    Promise.all(animations.map((animation) => animation.finished.catch(() => undefined))),
    new Promise((resolve) => setTimeout(resolve, LEAVE_DURATION_MS + 80)),
  ]);
  // the element may stay mounted (e.g. it only left another group): drop the "forwards" fill
  requestAnimationFrame(() => animations.forEach((animation) => animation.cancel()));
};
