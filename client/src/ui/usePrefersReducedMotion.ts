import { useSyncExternalStore } from 'react';

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

/*
 * Read as an external store rather than mirrored into state by an effect. The media query
 * IS the source of truth; copying it into `useState` would render once with the wrong
 * answer and correct itself, which for the components that use this means briefly building
 * an animation for someone who asked not to have one.
 *
 * `GlobalStyle` zeroes CSS animation and transition durations under the same query, but it
 * cannot reach a canvas or a `requestAnimationFrame` loop. Anything that animates outside
 * CSS has to ask for itself, which is what this hook is for.
 *
 * jsdom implements no `matchMedia`, and this is not worth a polyfill in the test setup, so
 * both accessors fall back to "no preference expressed".
 */
function subscribe(onChange: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => {};

  const query = window.matchMedia(REDUCED_MOTION);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

function read(): boolean {
  if (typeof window.matchMedia !== 'function') return false;
  return window.matchMedia(REDUCED_MOTION).matches;
}

/** True when the visitor has asked their system for less motion. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}
