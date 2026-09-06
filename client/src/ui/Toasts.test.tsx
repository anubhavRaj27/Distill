import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from 'styled-components';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { theme } from './theme';
import { Toasts } from './Toasts';
import { useToasts } from './toastStore';

/**
 * The toast stack.
 *
 * What is worth holding here is not that a box appears: it is that the box is announced,
 * that it leaves on its own, and that it can be got rid of by hand before it does — a timer
 * is a guess about reading speed.
 */

function renderToasts() {
  render(
    <ThemeProvider theme={theme}>
      <Toasts />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  useToasts.getState().clear();
});

afterEach(() => {
  vi.useRealTimers();
  useToasts.getState().clear();
});

describe('Toasts', () => {
  it('announces a message politely rather than stealing focus', () => {
    renderToasts();
    act(() => {
      useToasts.getState().show('4 documents uploaded. Reading them now.');
    });

    const region = screen.getByRole('status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveTextContent('4 documents uploaded. Reading them now.');
    // Nothing here needs answering, so nothing here takes the keyboard.
    expect(document.activeElement).toBe(document.body);
  });

  it('leaves on its own', () => {
    vi.useFakeTimers();
    renderToasts();
    act(() => {
      useToasts.getState().show('Uploaded.', { duration: 1000 });
    });

    expect(screen.getByText('Uploaded.')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.queryByText('Uploaded.')).not.toBeInTheDocument();
  });

  it('can be dismissed before the timer, for anyone reading at their own pace', async () => {
    const user = userEvent.setup();
    renderToasts();
    act(() => {
      useToasts.getState().show('Uploaded.');
    });

    await user.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(screen.queryByText('Uploaded.')).not.toBeInTheDocument();
  });

  it('keeps a stack rather than a log', () => {
    renderToasts();
    act(() => {
      const { show } = useToasts.getState();
      show('one');
      show('two');
      show('three');
      show('four');
    });

    // The oldest is dropped: four notices stacked over a screen is a wall, not a hint.
    expect(screen.queryByText('one')).not.toBeInTheDocument();
    expect(screen.getByText('four')).toBeInTheDocument();
    expect(useToasts.getState().toasts).toHaveLength(3);
  });

  it('marks a warning differently from a confirmation, and keeps it up longer', () => {
    act(() => {
      useToasts.getState().show('Two files could not be sent.', { tone: 'warning' });
    });
    const [toast] = useToasts.getState().toasts;
    expect(toast?.tone).toBe('warning');
    expect(toast?.duration).toBeGreaterThan(5000);
  });
});
