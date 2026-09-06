import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  APPEARANCE_STORAGE_KEY,
  AppearanceContext,
  DARK_QUERY,
  readStoredPreference,
  readSystemPrefersDark,
  resolveMode,
  type Appearance,
  type ThemePreference,
} from './appearance';

/**
 * Holds the appearance preference and turns it into a palette. Decision D88.
 *
 * The vocabulary and the decision rules are in `appearance.ts`; what is here is only the
 * three things that need a running browser — remembering the choice, watching the system,
 * and handing the root element over from the pre-mount script.
 */
export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [preference, setStoredPreference] = useState<ThemePreference>(readStoredPreference);
  const [systemPrefersDark, setSystemPrefersDark] = useState(readSystemPrefersDark);

  /*
   * The system's answer is watched, not merely read once. Somebody on the automatic setting
   * who is still here at sunset should see the page turn over without reloading it, and
   * that only happens if we are listening.
   */
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => setSystemPrefersDark(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    setStoredPreference(next);
    try {
      window.localStorage.setItem(APPEARANCE_STORAGE_KEY, next);
    } catch {
      // The choice still applies to this tab; it just will not outlive it.
    }
  }, []);

  const mode = resolveMode(preference, systemPrefersDark);

  /*
   * Takes the root element over from the pre-mount script in `index.html`.
   *
   * That script paints the ground and sets `color-scheme` as inline styles, because inline
   * is the only thing that applies before a stylesheet exists. Inline also wins against
   * every stylesheet forever after, so the first thing to do once `GlobalStyle` is mounted
   * is to take those two declarations off again: left in place they would pin the page to
   * whatever palette the visitor arrived on, and flipping the switch would change every
   * colour except the ground behind an over-scroll. The attribute stays, so anything
   * outside the React tree can still read which way round the page is.
   */
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = mode;
    root.style.removeProperty('color-scheme');
    root.style.removeProperty('background');
  }, [mode]);

  const value = useMemo<Appearance>(
    () => ({ preference, mode, setPreference }),
    [preference, mode, setPreference],
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}
