import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { ThemeProvider } from 'styled-components';
import { describe, expect, it, vi } from 'vitest';

import { AppearanceProvider } from '../ui/AppearanceProvider';
import { theme } from '../ui/theme';
import { AppHeader } from './AppHeader';

/**
 * The workspace name in the chrome, which is a label almost always and a text field
 * occasionally.
 *
 * What these hold: that renaming is possible at all, that abandoning an edit abandons it,
 * and that an empty name cannot be saved — an unnamed workspace and one deliberately called
 * nothing must stay distinguishable.
 */

/**
 * The header carries the appearance switch, and `useAppearance` refuses to run without a
 * provider on purpose, so the wrapper is here rather than a default context that would let
 * a missing provider pass for a dead button.
 */
function renderHeader(onRename?: (label: string) => void) {
  render(
    <AppearanceProvider>
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <AppHeader
            active="chat"
            workspace={{ id: 'w1', label: 'Acme invoices, Q1', documentCount: 4 }}
            onRename={onRename}
          />
        </MemoryRouter>
      </ThemeProvider>
    </AppearanceProvider>,
  );
}

describe('AppHeader workspace name', () => {
  it('shows the name and offers to change it', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    renderHeader(onRename);

    await user.click(screen.getByRole('button', { name: /acme invoices, q1/i }));
    const input = screen.getByRole('textbox', { name: /workspace name/i });
    expect(input).toHaveValue('Acme invoices, Q1');

    await user.clear(input);
    await user.type(input, 'Q1 vendor invoices{Enter}');
    expect(onRename).toHaveBeenCalledWith('Q1 vendor invoices');
  });

  it('abandons an edit on Escape without renaming anything', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    renderHeader(onRename);

    await user.click(screen.getByRole('button', { name: /acme invoices/i }));
    await user.type(screen.getByRole('textbox', { name: /workspace name/i }), ' and more');
    await user.keyboard('{Escape}');

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /acme invoices, q1/i })).toBeInTheDocument();
  });

  it('refuses to save an empty name', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    renderHeader(onRename);

    await user.click(screen.getByRole('button', { name: /acme invoices/i }));
    await user.clear(screen.getByRole('textbox', { name: /workspace name/i }));
    await user.keyboard('{Enter}');

    // Nothing written, and the old name is still there.
    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /acme invoices, q1/i })).toBeInTheDocument();
  });

  it('shows the name as plain text where it cannot be written', () => {
    renderHeader(undefined);
    expect(screen.queryByRole('button', { name: /acme invoices/i })).toBeNull();
    expect(screen.getByText('Acme invoices, Q1')).toBeInTheDocument();
  });
});

describe('AppHeader wordmark', () => {
  it('links back to the upload screen for this workspace', () => {
    renderHeader();

    // Its accessible name is the visible one, which is what a home link should be called.
    const home = screen.getByRole('link', { name: /distill/i });
    expect(home).toHaveAttribute('href', '/w/w1/upload');
  });

  it('points at the front door when there is no workspace yet', () => {
    render(
      <AppearanceProvider>
        <ThemeProvider theme={theme}>
          <MemoryRouter>
            <AppHeader />
          </MemoryRouter>
        </ThemeProvider>
      </AppearanceProvider>,
    );

    expect(screen.getByRole('link', { name: /distill/i })).toHaveAttribute('href', '/');
  });
});
