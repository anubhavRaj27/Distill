import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { act } from 'react';
import { ThemeProvider } from 'styled-components';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  APPEARANCE_STORAGE_KEY,
  parsePreference,
  resolveMode,
  useAppearance,
} from './appearance';
import { AppearanceProvider } from './AppearanceProvider';
import { AppearanceSwitch } from './AppearanceSwitch';
import { theme } from './theme';

/**
 * What these hold, in order of how much they would cost to get wrong:
 *
 * - The automatic setting stays automatic. Storing a resolved palette instead of the
 *   preference is the mistake that makes "match my system" a one-way door, and it is
 *   invisible until somebody's laptop changes mode and the page does not.
 * - A choice outlives the tab, and a browser that refuses to store it still renders.
 */

const listeners = new Set<(event: MediaQueryListEvent) => void>();

/** A `matchMedia` we can turn dark on demand, since jsdom's answer is always false. */
function stubMatchMedia(prefersDark: boolean) {
  listeners.clear();
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      media: query,
      matches: query.includes('prefers-color-scheme: dark') ? prefersDark : false,
      addEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) =>
        listeners.add(listener),
      removeEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) =>
        listeners.delete(listener),
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
      onchange: null,
    })),
  );
}

function systemTurnsDark(matches: boolean) {
  act(() => {
    for (const listener of listeners) listener({ matches } as MediaQueryListEvent);
  });
}

/** Prints the resolved palette, which is the only thing the rest of the app consumes. */
function Readout() {
  const { mode, preference } = useAppearance();
  return <output>{`${preference} → ${mode}`}</output>;
}

/*
 * A fixed palette under the provider on purpose. What is under test is which mode the
 * provider arrives at and what it writes down, not what the mode looks like once it gets
 * there; `theme.test.ts` covers the palettes themselves.
 */
function mount() {
  render(
    <AppearanceProvider>
      <ThemeProvider theme={theme}>
        <Readout />
        <AppearanceSwitch />
      </ThemeProvider>
    </AppearanceProvider>,
  );
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute('data-theme');
});

describe('resolving a preference', () => {
  it('follows the system only when asked to', () => {
    expect(resolveMode('system', true)).toBe('dark');
    expect(resolveMode('system', false)).toBe('light');
    expect(resolveMode('light', true)).toBe('light');
    expect(resolveMode('dark', false)).toBe('dark');
  });

  it('treats anything it does not recognise as the automatic setting', () => {
    // What comes back from storage is whatever the last version of the app wrote there.
    expect(parsePreference(null)).toBe('system');
    expect(parsePreference('midnight')).toBe('system');
    expect(parsePreference('dark')).toBe('dark');
  });
});

describe('the appearance switch', () => {
  it('starts on the system setting and takes the system palette', () => {
    stubMatchMedia(true);
    mount();

    expect(screen.getByText('system → dark')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /match my system/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('keeps following the system after it changes, without a reload', () => {
    stubMatchMedia(false);
    mount();
    expect(screen.getByText('system → light')).toBeInTheDocument();

    systemTurnsDark(true);
    expect(screen.getByText('system → dark')).toBeInTheDocument();
  });

  it('stores the choice, not the palette it resolved to', async () => {
    const user = userEvent.setup();
    stubMatchMedia(true);
    mount();

    await user.click(screen.getByRole('button', { name: 'Light' }));
    expect(screen.getByText('light → light')).toBeInTheDocument();
    expect(window.localStorage.getItem(APPEARANCE_STORAGE_KEY)).toBe('light');

    // And back: the automatic setting is somewhere you can return to.
    await user.click(screen.getByRole('button', { name: /match my system/i }));
    expect(screen.getByText('system → dark')).toBeInTheDocument();
    expect(window.localStorage.getItem(APPEARANCE_STORAGE_KEY)).toBe('system');
  });

  it('reads the stored choice back on the next visit', () => {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, 'dark');
    stubMatchMedia(false);
    mount();

    expect(screen.getByText('dark → dark')).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('still renders when the browser refuses to store anything', async () => {
    const user = userEvent.setup();
    stubMatchMedia(false);
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('storage is disabled');
      });

    mount();
    await user.click(screen.getByRole('button', { name: 'Dark' }));

    // The choice applies to this tab; it just will not outlive it.
    expect(screen.getByText('dark → dark')).toBeInTheDocument();
    setItem.mockRestore();
  });
});
