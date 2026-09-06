import { createContext, useContext } from 'react';

import type { ThemeMode } from './theme';

/**
 * Which palette the application is wearing, and who decided.
 *
 * There are three preferences and two modes, and keeping them apart is the whole design.
 * A *preference* is what the person chose — including "system", which is a choice not to
 * choose. A *mode* is the palette that follows from it right now. Storing the resolved mode
 * instead would freeze a visitor's palette at whatever their laptop happened to be doing
 * the first time they arrived, and it would never follow them into the evening again.
 *
 * The state itself lives in `AppearanceProvider`. This file is the part with no React in
 * it worth speaking of: the vocabulary, the two pure functions that decide everything, and
 * the hook to read the answer.
 *
 *
 */

export type ThemePreference = ThemeMode | 'system';

/**
 * The localStorage key.
 *
 * Also written, by hand, in the small script at the top of `index.html` that paints the
 * ground before React has mounted. Those two must agree; the comment in `index.html` says
 * so from the other side.
 */
export const APPEARANCE_STORAGE_KEY = 'distill.appearance';

/** The media query both the provider and the pre-mount script ask. */
export const DARK_QUERY = '(prefers-color-scheme: dark)';

const PREFERENCES: readonly ThemePreference[] = ['light', 'system', 'dark'];

/** Narrows whatever came back out of storage. Anything unrecognised means "system". */
export function parsePreference(value: string | null | undefined): ThemePreference {
  return PREFERENCES.includes(value as ThemePreference)
    ? (value as ThemePreference)
    : 'system';
}

/** The preference plus the current state of the world gives the palette to render. */
export function resolveMode(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ThemeMode {
  if (preference === 'system') return systemPrefersDark ? 'dark' : 'light';
  return preference;
}

export function readStoredPreference(): ThemePreference {
  try {
    return parsePreference(window.localStorage.getItem(APPEARANCE_STORAGE_KEY));
  } catch {
    // Private browsing, or storage disabled entirely. Not a reason to fail to render.
    return 'system';
  }
}

export function readSystemPrefersDark(): boolean {
  return typeof window.matchMedia === 'function'
    ? window.matchMedia(DARK_QUERY).matches
    : false;
}

export interface Appearance {
  /** What the person chose, "system" included. */
  preference: ThemePreference;
  /** The palette that follows from it. */
  mode: ThemeMode;
  setPreference: (next: ThemePreference) => void;
}

export const AppearanceContext = createContext<Appearance | null>(null);

/**
 * Reads the current appearance. Throws if there is no provider above it.
 *
 * The tempting alternative — a default context holding an inert `setPreference` — was
 * written first and is a trap. A switch under it renders perfectly, highlights nothing when
 * clicked, and reports no error: precisely the symptom of a missing provider, and
 * indistinguishable from a styling bug. Failing loudly costs one wrapper in one test file
 * and buys a mistake that announces itself.
 */
export function useAppearance(): Appearance {
  const value = useContext(AppearanceContext);
  if (value === null) {
    throw new Error('useAppearance was called outside an AppearanceProvider.');
  }
  return value;
}
