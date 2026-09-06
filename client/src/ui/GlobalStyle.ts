import { createGlobalStyle } from 'styled-components';

/**
 * Document-level styling and the CSS custom properties every component draws from.
 *
 * Tokens are emitted onto `:root` rather than read through `props.theme` at every call
 * site, because the virtualised table has to vary its appearance per cell without
 * generating a styled-components class per distinct value. Static styled components plus
 * `data-` attributes plus these variables is the pattern that keeps 5,000 rows smooth
 * (implementation.md section 2.3).
 *
 * The whole block is a function of `theme`, so switching palettes is one re-render of one
 * component: the variables change value in place and every rule that reads them follows,
 * including the ones inside components that never re-rendered. That is why dark mode did
 * not need a second stylesheet.
 */
export const GlobalStyle = createGlobalStyle`
  :root {
    --paper: ${({ theme }) => theme.color.paper};
    --paper-raised: ${({ theme }) => theme.color.paperRaised};
    --paper-sunken: ${({ theme }) => theme.color.paperSunken};
    --ink: ${({ theme }) => theme.color.ink};
    --ink-muted: ${({ theme }) => theme.color.inkMuted};
    --line: ${({ theme }) => theme.color.line};
    --line-strong: ${({ theme }) => theme.color.lineStrong};

    --ink-surface: ${({ theme }) => theme.color.inkSurface};
    --ink-surface-hover: ${({ theme }) => theme.color.inkSurfaceHover};
    --on-ink: ${({ theme }) => theme.color.onInk};
    --on-ink-wash: ${({ theme }) => theme.color.onInkWash};
    --ring: ${({ theme }) => theme.color.ring};
    --highlight: ${({ theme }) => theme.color.highlight};

    --stock-lightest: ${({ theme }) => theme.color.stock.lightest};
    --stock-light: ${({ theme }) => theme.color.stock.light};
    --stock-mid: ${({ theme }) => theme.color.stock.mid};
    --stock-heavy: ${({ theme }) => theme.color.stock.heavy};

    --tier-high: ${({ theme }) => theme.tier.high.color};
    --tier-medium: ${({ theme }) => theme.tier.medium.color};
    --tier-low: ${({ theme }) => theme.tier.low.color};
    --tier-conflict: ${({ theme }) => theme.tier.conflict.color};
    --tier-verified: ${({ theme }) => theme.tier.verified.color};

    --font-display: ${({ theme }) => theme.font.display};
    --font-body: ${({ theme }) => theme.font.body};
    --font-mono: ${({ theme }) => theme.font.mono};

    /*
     * Tells the browser which way round this page is, which is the only way to get its own
     * furniture to follow: scrollbars, the default form control chrome, and the ground it
     * paints behind an over-scroll.
     */
    color-scheme: ${({ theme }) => theme.mode};
  }

  *, *::before, *::after {
    box-sizing: border-box;
  }

  html, body, #root {
    height: 100%;
  }

  /*
   * The ground is set on the root element as well as on the body. The pre-mount script in
   * index.html paints it there to avoid a flash of the wrong palette, and this is what
   * takes that inline style over once the application is running.
   */
  html {
    background: var(--paper);
  }

  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: var(--font-body);
    font-size: 16px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;

    /*
     * A short cross-fade on the two properties the whole page shares, so flipping the
     * switch reads as the light changing rather than as a new page arriving. Only these
     * two: transitioning every colour in the app would mean animating several thousand
     * table cells at once. The reduced-motion block below cancels it.
     */
    transition:
      background-color ${({ theme }) => theme.motion.quick},
      color ${({ theme }) => theme.motion.quick};
  }

  h1, h2, h3, p, figure {
    margin: 0;
  }

  /*
   * Focus is never removed, only restyled. The :focus-visible selector keeps the ring off
   * mouse clicks while guaranteeing it for keyboard users, which the review flow depends
   * on entirely (requirement FR-33).
   *
   * Note for anyone editing the CSS below: this is a template literal, so a backtick in a
   * comment terminates the string. Prose inside these blocks stays unquoted.
   */
  :focus-visible {
    outline: 2px solid ${({ theme }) => theme.color.focus};
    outline-offset: 2px;
    border-radius: ${({ theme }) => theme.radius.sm};
  }

  /*
   * Motion in this product exists to show data settling into place. When a person has
   * asked their system for less of it, there is nothing left worth animating.
   */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
`;
