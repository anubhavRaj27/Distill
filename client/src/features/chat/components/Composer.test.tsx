import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Providers } from '../../../app/Providers';
import { makeQueryClient } from '../../../app/queryClient';
import { Composer } from './Composer';

/**
 * The question box.
 *
 * The height test exists because of a real bug: the box arrived pinned open at its 180px
 * ceiling, because the auto-resize measured `scrollHeight` once on mount — before layout
 * had settled — wrote the result as an inline height, and then never remeasured, since the
 * value had not changed. jsdom has no layout to reproduce the bad measurement, but it can
 * hold the fix that matters: an empty box carries no inline height at all and is sized by
 * CSS.
 */

function Harness({ onAsk = () => {} }: { onAsk?: (question: string) => void }) {
  const [value, setValue] = useState('');
  return <Composer value={value} onChange={setValue} onAsk={onAsk} />;
}

function renderComposer(onAsk?: (question: string) => void) {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <Harness onAsk={onAsk} />
    </Providers>,
  );
}

const field = () => screen.getByRole('textbox', { name: /ask about these documents/i });

describe('Composer', () => {
  it('leaves an empty box to be sized by CSS', () => {
    renderComposer();

    expect(field().style.height).toBe('');
  });

  it('returns to that state after a question is sent', async () => {
    const user = userEvent.setup();
    renderComposer();

    await user.type(field(), 'a question');
    await user.click(screen.getByRole('button', { name: /send question/i }));

    expect(field()).toHaveValue('');
    expect(field().style.height).toBe('');
  });

  it('sends on Enter and breaks the line on Shift+Enter', async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    renderComposer(onAsk);

    await user.type(field(), 'first line{Shift>}{Enter}{/Shift}second line');
    expect(onAsk).not.toHaveBeenCalled();
    expect(field()).toHaveValue('first line\nsecond line');

    await user.type(field(), '{Enter}');
    expect(onAsk).toHaveBeenCalledWith('first line\nsecond line');
  });

  it('will not send whitespace', async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    renderComposer(onAsk);

    await user.type(field(), '   ');
    expect(screen.getByRole('button', { name: /send question/i })).toBeDisabled();

    await user.type(field(), '{Enter}');
    expect(onAsk).not.toHaveBeenCalled();
  });
});
