import { describe, expect, it } from 'vitest';

import { theme } from './theme';

/**
 * The accessibility requirement names a 4.5:1 minimum contrast ratio for text (WCAG 2.1
 * AA). That is the kind of promise that quietly stops being true the first time somebody
 * warms up a grey, so it is asserted here against the tokens themselves rather than left
 * to a manual audit at the end.
 *
 * The tier colours are included because they are used for text and glyphs, not only for
 * borders — a low-confidence marker nobody can read is worse than no marker.
 */

function channel(value: number): number {
  const srgb = value / 255;
  return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const value = hex.replace('#', '');
  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  const [lighter, darker] = a > b ? [a, b] : [b, a];
  return (lighter + 0.05) / (darker + 0.05);
}

const AA_NORMAL_TEXT = 4.5;

describe('theme contrast', () => {
  const pairs: Array<[label: string, foreground: string, background: string]> = [
    ['body text on paper', theme.color.ink, theme.color.paper],
    ['body text on a raised surface', theme.color.ink, theme.color.paperRaised],
    ['secondary text on paper', theme.color.inkMuted, theme.color.paper],
    ['secondary text on a raised surface', theme.color.inkMuted, theme.color.paperRaised],
    ['secondary text on sunken paper', theme.color.inkMuted, theme.color.paperSunken],
    ['primary button label', theme.color.onInk, theme.color.inkSurface],
    ['primary button label, hovered', theme.color.onInk, theme.color.inkSurfaceHover],
  ];

  for (const [label, foreground, background] of pairs) {
    it(`${label} meets AA`, () => {
      expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
    });
  }

  for (const [name, tier] of Object.entries(theme.tier)) {
    it(`the ${name} tier is readable on paper`, () => {
      expect(contrastRatio(tier.color, theme.color.paper)).toBeGreaterThanOrEqual(
        AA_NORMAL_TEXT,
      );
    });

    it(`the ${name} tier carries a mark and a label, not only a colour`, () => {
      // The hard constraint from the requirements: confidence is never conveyed by colour
      // alone. Every tier must offer at least two other channels to render.
      expect(tier.mark.length).toBeGreaterThan(0);
      expect(tier.label.length).toBeGreaterThan(0);
    });
  }
});
