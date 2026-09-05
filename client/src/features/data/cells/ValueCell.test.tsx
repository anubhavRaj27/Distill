import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from 'styled-components';
import { describe, expect, it, vi } from 'vitest';

import { theme } from '../../../ui/theme';
import { ValueCell } from './ValueCell';

/**
 * The cell is where a person checks a number against its source and, when it is wrong,
 * fixes it. These tests hold the two things that make that safe: the value is legible in
 * the shape its type deserves, and starting an edit replaces the old value rather than
 * appending to it.
 *
 * The append case is here because it shipped: the editor selected its text from a
 * microtask without focusing first, so the double-click's own focus won, the caret landed
 * at the end, and typing "Freight & Logistics" over "Freight" produced
 * "FreightFreight & Logistics". Caught in the browser, not by the suite.
 */

function renderCell(props: Partial<Parameters<typeof ValueCell>[0]> = {}) {
  const onCommit = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <ValueCell
        value={{
          field_key: 'category',
          value: 'Freight',
          value_type: 'string',
          tier: 'high',
          status: 'model',
        }}
        type="string"
        editing={false}
        onStartEdit={() => {}}
        onCancelEdit={() => {}}
        onCommit={onCommit}
        onOpenSource={() => {}}
        {...props}
      />
    </ThemeProvider>,
  );
  return { onCommit };
}

describe('ValueCell', () => {
  it('shows the value with its confidence named, not just coloured', () => {
    renderCell();

    expect(screen.getByText('Freight')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /high confidence/i })).toBeInTheDocument();
  });

  it('formats currency with grouped thousands and keeps the ISO code', () => {
    renderCell({
      type: 'currency',
      value: {
        field_key: 'total',
        value: { amount: 184200, currency: 'USD' },
        value_type: 'currency',
        tier: 'high',
        status: 'model',
      },
    });

    expect(screen.getByText('184,200.00 USD')).toBeInTheDocument();
  });

  it('renders an absent value as a dash rather than a zero', () => {
    renderCell({
      type: 'currency',
      value: { field_key: 'total', value: null, value_type: 'currency', tier: 'low', status: 'model' },
    });

    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows both readings and a way out when the values conflict', () => {
    renderCell({
      type: 'currency',
      value: {
        field_key: 'total',
        value: { amount: 99150, currency: 'USD' },
        model_value: { amount: 98400, currency: 'USD' },
        value_type: 'currency',
        tier: 'conflict',
        status: 'human_verified',
      },
    });

    expect(screen.getByText(/Model: 98,400.00 USD/)).toBeInTheDocument();
    expect(screen.getByText(/Human: 99,150.00 USD/)).toBeInTheDocument();
    expect(screen.getByText(/Conflicting values/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resolve/i })).toBeInTheDocument();
  });

  it('selects the existing value when an edit opens, so typing replaces it', async () => {
    const user = userEvent.setup();
    const { onCommit } = renderCell({ editing: true });

    const input = screen.getByRole('textbox', { name: /edit value/i });
    expect(input).toHaveFocus();

    await user.keyboard('Logistics{Enter}');

    // Not "FreightLogistics".
    expect(onCommit).toHaveBeenCalledWith('Logistics');
  });

  it('abandons an edit on Escape without committing', async () => {
    const user = userEvent.setup();
    const onCancelEdit = vi.fn();
    const { onCommit } = renderCell({ editing: true, onCancelEdit });

    await user.keyboard('nonsense{Escape}');

    expect(onCancelEdit).toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });
});
