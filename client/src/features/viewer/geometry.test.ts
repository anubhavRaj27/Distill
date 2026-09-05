import { describe, expect, it } from 'vitest';

import { highlightStyle } from './geometry';

/**
 * The overlay arithmetic, on its own.
 *
 * This exists because of a real bug rather than for coverage. The highlight boxes are
 * `x0/top/x1/bottom` in top-left-origin page points (`server/app/domain/geometry.py`);
 * the first version of this viewer read `y0/y1` off them, which are not fields, so every
 * rectangle got `NaN` for its vertical position. The browser drops a `NaN` in a `style`
 * without complaint, so six highlights rendered as six invisible divs and the panel looked
 * like a citation with nothing to point at. Nothing in the interface said otherwise.
 */

describe('highlightStyle', () => {
  it('scales page points into rendered pixels', () => {
    // A 612pt-wide page rendered 306px wide is a scale of 0.5.
    expect(highlightStyle({ x0: 54, top: 68, x1: 165, bottom: 80.5 }, 0.5)).toEqual({
      left: 27,
      top: 34,
      width: 55.5,
      height: 6.25,
    });
  });

  it('reads the vertical edges from top and bottom, which is what the server sends', () => {
    const style = highlightStyle({ x0: 0, top: 100, x1: 10, bottom: 120 }, 1)!;

    expect(style.top).toBe(100);
    expect(style.height).toBe(20);
  });

  it('keeps a hairline box visible', () => {
    // A thin rule or a single digit scales to well under a pixel at panel width.
    const style = highlightStyle({ x0: 10, top: 10, x1: 10.5, bottom: 10.4 }, 0.5)!;

    expect(style.width).toBe(2);
    expect(style.height).toBe(2);
  });

  it('refuses a box it cannot draw rather than emitting NaN', () => {
    const malformed = { x0: 1, x1: 2 } as unknown as Parameters<typeof highlightStyle>[0];

    expect(highlightStyle(malformed, 1)).toBeNull();
    // Scale is zero until the image has been measured; there is nothing to draw yet.
    expect(highlightStyle({ x0: 1, top: 1, x1: 2, bottom: 2 }, 0)).toBeNull();
  });
});
