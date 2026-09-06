/**
 * Design tokens for Distill, in two modes.
 *
 * The visual language is "distillation": crude, mixed input narrowing into something pure
 * and legible. Structurally that shows up as warm paper stock (documents) resolving into
 * ink on a ruled grid (the table). It is deliberately not the default AI-dashboard look —
 * no indigo-on-white, no card grid. See decision D22.
 *
 * Dark mode is the same idea turned over rather than a second design: the ink becomes the
 * ground and the paper becomes the mark. That is why the dark palette is a deep navy
 * charcoal rather than a neutral black — it is the light theme's ink colour, grown into a
 * page.
 *
 * Every token lives here and is emitted as a CSS custom property by `GlobalStyle`. Nothing
 * outside this file hard-codes a colour. That matters three times over now: it is what
 * makes the A2UI catalog inherit the app's look for free (requirement A2-02), it is what
 * lets the virtualised table drive its variants from `data-` attributes and CSS variables
 * rather than from interpolated props (implementation.md section 2.3), and it is what makes
 * a second palette a data change rather than a rewrite.
 */

export type ThemeMode = 'light' | 'dark';

export type Tier = 'high' | 'medium' | 'low' | 'conflict' | 'verified';

/**
 * Confidence tiers, the product's most important visual system.
 *
 * A hard constraint from the requirements: confidence is NEVER conveyed by colour alone.
 * Each tier therefore carries a `mark` (a glyph) and a `label` alongside its colour, and
 * components must render at least two of the three channels.
 *
 * The mark and the label are the two channels that do not depend on the palette, so they
 * live outside it. Only the colour is per-mode, which also means a mode cannot accidentally
 * ship a tier with no glyph.
 */
const TIER_CHANNELS: Record<Tier, { mark: string; label: string }> = {
  high: { mark: '●', label: 'High confidence' },
  medium: { mark: '◐', label: 'Medium confidence' },
  low: { mark: '○', label: 'Low confidence' },
  conflict: { mark: '⌁', label: 'Conflicting values' },
  verified: { mark: '✓', label: 'Verified by a person' },
};

interface Palette {
  color: {
    /** Page ground. */
    paper: string;
    /** Raised surfaces sitting on the paper: document cards, the result table. */
    paperRaised: string;
    /** Slightly recessed paper, for the second document in a stack. */
    paperSunken: string;

    /** Primary text and the wordmark. */
    ink: string;
    /** Secondary text. Verified at 4.5:1 against every ground by ui/theme.test.ts. */
    inkMuted: string;

    /** Hairlines: table rules, the footer divider, document card edges. */
    line: string;
    /** A hairline that needs to be seen, e.g. the dashed drop zone. */
    lineStrong: string;

    /** Fills for the document illustration, lightest to heaviest. */
    stock: { lightest: string; light: string; mid: string; heavy: string };

    /** Inverted surfaces: the primary button, the current tab, a toast. */
    inkSurface: string;
    inkSurfaceHover: string;
    onInk: string;
    /** A hover wash on an inverted surface, expressed in the ink that sits on it. */
    onInkWash: string;

    /** Focus ring. Never removed, only restyled (accessibility NFR). */
    focus: string;
    /** The soft ring around a cell being edited. */
    ring: string;

    /**
     * A surface you can see through: the drop zone, which sits over the aurora.
     *
     * Expressed as a translucent version of `paperRaised` rather than as its own colour,
     * because that is exactly what it is — the same panel, letting some of what is behind
     * it come through. `glassDragging` is the same surface a shade more solid, so the zone
     * still visibly firms up when a file is over it.
     *
     * **The alpha is a contrast budget, not a taste.** Whatever shows through has to leave
     * the panel's own text above 4.5:1, and the two palettes have wildly different room.
     * Dark has almost none: the text on this panel is pale, the aurora's overlapping ribbons
     * can reach white, and pale-on-white is where a glass panel fails — 0.52 measured 2.89:1
     * against a white backdrop, which is why it is not 0.52. Light has room to spare, since
     * its text is the darkest colour in the palette and the aurora only ever takes cream
     * down to a mid tone, so light is the more transparent of the two even though it looks
     * like it should be the other way round. `theme.test.ts` asserts both against the worst
     * backdrop each can face.
     */
    glass: string;
    glassDragging: string;

    /**
     * The drop zone's aurora. Decoration, and the only tokens here that carry no meaning.
     *
     * They are named rather than passed as props for the same reason every other colour is:
     * so a palette owns its own appearance, and so a reader looking for what colours this
     * product uses finds all of them in one file. `base` and `mid` are the ground the
     * shader starts from; `sheen` and `accent` are the two ribbon hues. Because they say
     * nothing, they are the one group exempt from the contrast table — no text is ever
     * placed on them, which the scrim in `SilkAurora` is what guarantees.
     */
    aurora: { base: string; mid: string; sheen: string; accent: string };

    /**
     * The source viewer's highlighter.
     *
     * This one does not invert, and that is the point: it is painted in `multiply` over a
     * raster of the page, which is a photograph of white paper in either mode. A dark
     * highlighter would black out the words it is meant to draw attention to.
     */
    highlight: string;
  };

  /** Tier colours only. The mark and the label come from `TIER_CHANNELS`. */
  tier: Record<Tier, string>;

  shadow: {
    /** Paper lifting off paper. Barely there on purpose. */
    card: string;
    raised: string;
    /**
     * Off the page entirely, for the one element that floats over everything: the toast
     * stack. Heavier than `raised` because it has to read as being in front
     * of the page rather than part of it.
     */
    lifted: string;
  };
}

const light: Palette = {
  color: {
    /** Warm rather than white: this is paper, not a screen. */
    paper: '#FAF8F5',
    paperRaised: '#FFFFFF',
    paperSunken: '#F0ECE5',

    /** A navy that reads as ink, not as brand blue. */
    ink: '#1A2238',
    inkMuted: '#6B6760',

    line: '#E2DDD5',
    lineStrong: '#C7C0B5',

    stock: {
      lightest: '#F2EEE7',
      light: '#EAE5DD',
      mid: '#DCD6CC',
      heavy: '#CFC7BA',
    },

    inkSurface: '#1A2238',
    inkSurfaceHover: '#2A3350',
    onInk: '#FFFFFF',
    onInkWash: 'rgba(255, 255, 255, 0.12)',

    focus: '#1A2238',
    ring: 'rgba(26, 34, 56, 0.2)',

    highlight: 'rgba(214, 178, 74, 0.42)',

    glass: 'rgba(255, 255, 255, 0.38)',
    glassDragging: 'rgba(240, 236, 229, 0.8)',

    /*
     * Cream, going a shade deeper, washed with gold and sage.
     *
     * The shader subtracts these on a light ground, so what is named here is the colour a
     * ribbon *leaves behind*, not the light it adds — and that is why these two are far more
     * saturated than they look on the panel. Subtraction removes a tint's complement, so a
     * pale tint has a pale complement, removes roughly the same amount from all three
     * channels, and produces grey. The first attempt here used a soft sage and a soft
     * champagne and the whole panel came out the colour of dishwater. Saturated in, muted
     * out.
     */
    aurora: {
      base: '#FBF9F6',
      mid: '#F4F0E9',
      sheen: '#D9B44A',
      accent: '#79BFB1',
    },
  },

  tier: {
    high: '#2F6F4E',
    medium: '#8A6A1F',
    low: '#9A4B2A',
    conflict: '#8C2F39',
    verified: '#1F6B57',
  },

  shadow: {
    card: '0 1px 2px rgba(26, 34, 56, 0.06)',
    raised: '0 2px 8px rgba(26, 34, 56, 0.08)',
    lifted: '0 6px 24px rgba(26, 34, 56, 0.18)',
  },
};

/**
 * The same page, at night.
 *
 * Two rules held the palette together. The ground is the light theme's ink hue carried
 * down, not a neutral grey, so the product still looks like itself. And the inversion is
 * carried all the way through: `inkSurface` is now the pale surface and `onInk` the dark
 * text on it, so a primary button, a current tab and a toast stay the loudest things on
 * the screen without any component knowing which mode it is in.
 *
 * The tier colours are lifted and desaturated rather than reused. The light theme's forest
 * green on this ground is a smudge; these are the same five hues at a luminance that clears
 * 4.5:1 on both the paper and the raised surface, which `theme.test.ts` asserts.
 */
const dark: Palette = {
  color: {
    paper: '#12151F',
    paperRaised: '#191D2A',
    paperSunken: '#0C0F16',

    ink: '#EDEAE4',
    inkMuted: '#8E93A2',

    line: '#272C3A',
    lineStrong: '#3B4152',

    stock: {
      lightest: '#1B2030',
      light: '#222839',
      mid: '#2B3142',
      heavy: '#394052',
    },

    inkSurface: '#EDEAE4',
    inkSurfaceHover: '#FFFFFF',
    onInk: '#12151F',
    onInkWash: 'rgba(18, 21, 31, 0.12)',

    focus: '#EDEAE4',
    ring: 'rgba(237, 234, 228, 0.24)',

    /* Unchanged, and deliberately so. See the field's comment on `Palette`. */
    highlight: 'rgba(214, 178, 74, 0.42)',

    glass: 'rgba(25, 29, 42, 0.75)',
    glassDragging: 'rgba(12, 15, 22, 0.9)',

    /* Champagne and mint over ink, which is upstream's pairing and needed no changing. */
    aurora: {
      base: '#0F121B',
      mid: '#191D2A',
      sheen: '#F4DFB8',
      accent: '#6ED6C9',
    },
  },

  tier: {
    high: '#5FBF8A',
    medium: '#D2AC5B',
    low: '#E0906A',
    conflict: '#E8737F',
    verified: '#5CC7AC',
  },

  /*
   * Shadow on a dark ground is a different physical claim: there is no light to occlude, so
   * these read as depth only if they are near-black and larger. A shadow tuned for paper
   * simply disappears here.
   */
  shadow: {
    card: '0 1px 2px rgba(0, 0, 0, 0.4)',
    raised: '0 2px 10px rgba(0, 0, 0, 0.45)',
    lifted: '0 8px 30px rgba(0, 0, 0, 0.6)',
  },
};

/** Everything that is the same in both modes: type, rhythm, geometry, timing. */
const structure = {
  font: {
    /**
     * Display face, for headlines only. A transitional serif carries the "considered
     * instrument" register the creative direction asks for, and separates the product's
     * voice from its data. System faces only, so a cold start renders correct type with no
     * network round-trip and the one-command setup stays one command. See decision D22.
     */
    display:
      "'Iowan Old Style', 'Palatino Linotype', Palatino, 'Book Antiqua', Georgia, serif",
    /** Interface face. */
    body: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    /** Values, identifiers, generated SQL. Tabular figures matter for a column of money. */
    mono: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
  },

  /** A 4px rhythm. Named by use, not by number, so intent survives a redesign. */
  space: {
    xs: '4px',
    sm: '8px',
    md: '12px',
    lg: '16px',
    xl: '24px',
    xxl: '32px',
    section: '48px',
    page: '48px',
  },

  radius: {
    sm: '3px',
    md: '6px',
    pill: '999px',
  },

  /** Widths the layout is built around. Desktop-first, per the requirements. */
  measure: {
    /** Reading width for the hero copy and the drop zone. */
    prose: '720px',
    narrow: '600px',
  },

  motion: {
    /**
     * Motion is restrained and always has a reason: data settling into place, a highlight
     * arriving on a document region. Every animation in the app is wrapped in a
     * `prefers-reduced-motion` guard by `GlobalStyle`.
     */
    settle: '520ms cubic-bezier(0.2, 0.7, 0.3, 1)',
    quick: '140ms ease-out',
  },
} as const;

function makeTheme(mode: ThemeMode, palette: Palette) {
  return {
    /**
     * Which palette this is. Read by `GlobalStyle` to set `color-scheme`, so the browser's
     * own furniture — scrollbars, form controls, the canvas behind a rubber-band scroll —
     * matches the page instead of staying stubbornly white.
     */
    mode,
    color: palette.color,
    shadow: palette.shadow,
    tier: {
      high: { color: palette.tier.high, ...TIER_CHANNELS.high },
      medium: { color: palette.tier.medium, ...TIER_CHANNELS.medium },
      low: { color: palette.tier.low, ...TIER_CHANNELS.low },
      conflict: { color: palette.tier.conflict, ...TIER_CHANNELS.conflict },
      verified: { color: palette.tier.verified, ...TIER_CHANNELS.verified },
    },
    ...structure,
  };
}

export const lightTheme = makeTheme('light', light);
export const darkTheme = makeTheme('dark', dark);

export const themes: Record<ThemeMode, Theme> = {
  light: lightTheme,
  dark: darkTheme,
};

/**
 * The default theme.
 *
 * Kept as a named export because a handful of call sites want a token that no palette
 * changes — a tier's glyph, the display face — and because every test that mounts a
 * component under a `ThemeProvider` needs one theme to hand without caring which.
 */
export const theme = lightTheme;

export type Theme = ReturnType<typeof makeTheme>;
