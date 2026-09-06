import { describe, expect, it } from 'vitest';

import { darkTheme, lightTheme, type Theme } from './theme';

/**
 * The accessibility requirement names a 4.5:1 minimum contrast ratio for text (WCAG 2.1
 * AA). That is the kind of promise that quietly stops being true the first time somebody
 * warms up a grey, so it is asserted here against the tokens themselves rather than left
 * to a manual audit at the end.
 *
 * Both palettes are put through the same table. A second theme is the easiest way in the
 * world to ship an inaccessible one — the light theme was measured, the dark theme was
 * eyeballed at night on a good monitor — and the only defence is that neither is allowed
 * to be special. See decision D88.
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

const PALETTES: Array<[name: string, theme: Theme]> = [
  ['light', lightTheme],
  ['dark', darkTheme],
];

describe.each(PALETTES)('the %s palette', (_name, theme) => {
  const pairs: Array<[label: string, foreground: string, background: string]> = [
    ['body text on paper', theme.color.ink, theme.color.paper],
    ['body text on a raised surface', theme.color.ink, theme.color.paperRaised],
    ['secondary text on paper', theme.color.inkMuted, theme.color.paper],
    ['secondary text on a raised surface', theme.color.inkMuted, theme.color.paperRaised],
    ['secondary text on sunken paper', theme.color.inkMuted, theme.color.paperSunken],
    ['primary button label', theme.color.onInk, theme.color.inkSurface],
    ['primary button label, hovered', theme.color.onInk, theme.color.inkSurfaceHover],
    // The warning toast, which is the one place text sits on a tier colour rather than
    // beside one.
    ['a warning toast', theme.color.onInk, theme.tier.conflict.color],
  ];

  for (const [label, foreground, background] of pairs) {
    it(`${label} meets AA`, () => {
      expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
    });
  }

  for (const [name, tier] of Object.entries(theme.tier)) {
    it(`the ${name} tier is readable on both grounds`, () => {
      // Raised as well as paper: the table the tier marks live in is a raised surface, and
      // in the dark palette the two grounds are far enough apart to matter.
      expect(contrastRatio(tier.color, theme.color.paper)).toBeGreaterThanOrEqual(
        AA_NORMAL_TEXT,
      );
      expect(contrastRatio(tier.color, theme.color.paperRaised)).toBeGreaterThanOrEqual(
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

describe('the two palettes', () => {
  /*
   * The failure this catches is the boring one that would actually happen: somebody adds a
   * token to the light theme, wires it into a component, and never opens the file in dark
   * mode. The component then renders `undefined` as a colour, which is transparent, and
   * nothing anywhere throws.
   */
  it('define exactly the same tokens', () => {
    const shape = (value: unknown, path = ''): string[] =>
      value !== null && typeof value === 'object'
        ? Object.entries(value).flatMap(([key, child]) => shape(child, `${path}.${key}`))
        : [path];

    expect(shape(darkTheme.color).sort()).toEqual(shape(lightTheme.color).sort());
    expect(shape(darkTheme.shadow).sort()).toEqual(shape(lightTheme.shadow).sort());
    expect(shape(darkTheme.tier).sort()).toEqual(shape(lightTheme.tier).sort());
  });

  it('know which one they are', () => {
    // GlobalStyle emits this as `color-scheme`, which is what makes the browser's own
    // scrollbars and form controls follow the page.
    expect(lightTheme.mode).toBe('light');
    expect(darkTheme.mode).toBe('dark');
  });

  it('agree on the glyphs, which no palette is allowed to change', () => {
    for (const tier of ['high', 'medium', 'low', 'conflict', 'verified'] as const) {
      expect(darkTheme.tier[tier].mark).toBe(lightTheme.tier[tier].mark);
      expect(darkTheme.tier[tier].label).toBe(lightTheme.tier[tier].label);
    }
  });
});
