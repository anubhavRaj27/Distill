import type { BBox } from '../chat/answerStream';

/**
 * Where one highlight sits over the rendered page, or null if it cannot be drawn.
 *
 * Pulled out of the render and exported so it can be tested directly, because this is the
 * one calculation in the viewer that fails *silently*: a `NaN` in a `style` is dropped by
 * the browser, so a box computed from the wrong fields renders as an invisible highlight
 * and the panel simply looks like it had nothing to show. That is exactly the bug this
 * function was extracted after — the boxes are `x0/top/x1/bottom` in top-left-origin page
 * points, and reading `y0/y1` off them produced six perfectly positioned nothings.
 */
export function highlightStyle(
  box: BBox,
  scale: number,
): { left: number; top: number; width: number; height: number } | null {
  const finite =
    Number.isFinite(box.x0) &&
    Number.isFinite(box.top) &&
    Number.isFinite(box.x1) &&
    Number.isFinite(box.bottom);
  if (!finite || !Number.isFinite(scale) || scale <= 0) return null;

  return {
    left: box.x0 * scale,
    top: box.top * scale,
    // A hairline box — a thin rule, a single digit — still has to be visible.
    width: Math.max(2, (box.x1 - box.x0) * scale),
    height: Math.max(2, (box.bottom - box.top) * scale),
  };
}
