/**
 * Design tokens for Distill.
 *
 * The visual language is "distillation": crude, mixed input narrowing into something pure
 * and legible. Structurally that shows up as warm paper stock (documents) resolving into
 * ink on a ruled grid (the table). It is deliberately not the default AI-dashboard look —
 * no indigo-on-white, no card grid. See decision D32.
 *
 * Every token lives here and is emitted as a CSS custom property by `GlobalStyle`. Nothing
 * outside this file hard-codes a colour. That matters twice over: it is what makes the
 * A2UI catalog inherit the app's look for free (requirement A2-02), and it is what lets the
 * virtualised table drive its variants from `data-` attributes and CSS variables rather
 * than from interpolated props, which is the performance constraint recorded in
 * implementation.md section 2.3.
 */

export const theme = {
  color: {
    /** Page ground. Warm rather than white: this is paper, not a screen. */
    paper: '#FAF8F5',
    /** Raised surfaces sitting on the paper: document cards, the result table. */
    paperRaised: '#FFFFFF',
    /** Slightly recessed paper, for the second document in a stack. */
    paperSunken: '#F0ECE5',

    /** Primary text and the wordmark. A navy that reads as ink, not as brand blue. */
    ink: '#1A2238',
    /** Secondary text. Verified at 4.5:1 against `paper` by ui/theme.test.ts. */
    inkMuted: '#6B6760',

    /** Hairlines: table rules, the footer divider, document card edges. */
    line: '#E2DDD5',
    /** A hairline that needs to be seen, e.g. the dashed drop zone. */
    lineStrong: '#C7C0B5',

    /** Fills for the document illustration, lightest to heaviest. */
    stock: {
      lightest: '#F2EEE7',
      light: '#EAE5DD',
      mid: '#DCD6CC',
      heavy: '#CFC7BA',
    },

    /** Inverted surfaces: the primary button. */
    inkSurface: '#1A2238',
    inkSurfaceHover: '#2A3350',
    onInk: '#FFFFFF',

    /** Focus ring. Never removed, only restyled (accessibility NFR). */
    focus: '#1A2238',
  },

  /**
   * Confidence tiers, the product's most important visual system.
   *
   * A hard constraint from the requirements: confidence is NEVER conveyed by colour alone.
   * Each tier therefore carries a `mark` (a glyph) and a `label` alongside its colour, and
   * components must render at least two of the three channels. These tokens are defined
   * here so the rule has one home, even though the table that consumes them is a later
   * screen.
   */
  tier: {
    high: { color: '#2F6F4E', mark: '●', label: 'High confidence' },
    medium: { color: '#8A6A1F', mark: '◐', label: 'Medium confidence' },
    low: { color: '#9A4B2A', mark: '○', label: 'Low confidence' },
    conflict: { color: '#8C2F39', mark: '⌁', label: 'Conflicting values' },
    verified: { color: '#1F6B57', mark: '✓', label: 'Verified by a person' },
  },

  font: {
    /**
     * Display face, for headlines only. A transitional serif carries the "considered
     * instrument" register the creative direction asks for, and separates the product's
     * voice from its data. System faces only, so a cold start renders correct type with no
     * network round-trip and the one-command setup stays one command. See decision D32.
     */
    display:
      "'Iowan Old Style', 'Palatino Linotype', Palatino, 'Book Antiqua', Georgia, serif",
    /** Interface face. */
    body:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
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

  shadow: {
    /** Paper lifting off paper. Barely there on purpose. */
    card: '0 1px 2px rgba(26, 34, 56, 0.06)',
    raised: '0 2px 8px rgba(26, 34, 56, 0.08)',
    /**
     * Off the page entirely, for the one element that floats over everything: the toast
     * stack (decision D73). Heavier than `raised` because it has to read as being in front
     * of the page rather than part of it, and it sits on ink rather than paper.
     */
    lifted: '0 6px 24px rgba(26, 34, 56, 0.18)',
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

export type Theme = typeof theme;
