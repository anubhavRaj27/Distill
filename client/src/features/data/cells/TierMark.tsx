import styled from 'styled-components';

import { theme } from '../../../ui/theme';

/**
 * The confidence marker that sits on every cell.
 *
 * The hard constraint from the requirements: confidence is **never** conveyed by colour
 * alone. Every tier therefore ships three channels — a colour, a distinct glyph shape, and
 * a text label — and this component always renders at least the glyph and the label, the
 * label through the accessible name so it reaches a screen reader and a tooltip without
 * taking any space in a dense table.
 *
 * The glyphs are chosen to differ in *fill* as well as colour, so they survive greyscale:
 * filled, half-filled, hollow, a bolt, a tick.
 */

export type Tier = 'high' | 'medium' | 'low' | 'conflict' | 'verified';

const Mark = styled.span`
  font-size: 10px;
  line-height: 1;
  user-select: none;

  &[data-tier='high'] {
    color: var(--tier-high);
  }
  &[data-tier='medium'] {
    color: var(--tier-medium);
  }
  &[data-tier='low'] {
    color: var(--tier-low);
  }
  &[data-tier='conflict'] {
    color: var(--tier-conflict);
  }
  &[data-tier='verified'] {
    color: var(--tier-verified);
  }
`;

export function TierMark({ tier }: { tier: Tier }) {
  const { mark, label } = theme.tier[tier];
  return (
    <Mark data-tier={tier} title={label} role="img" aria-label={label}>
      {mark}
    </Mark>
  );
}

/** The key beneath the table. Spells out what every glyph means, once. */
const LegendRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: ${({ theme }) => theme.space.md};

  padding-bottom: ${({ theme }) => theme.space.md};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  font-size: 11px;
  color: ${({ theme }) => theme.color.inkMuted};
  white-space: nowrap;
`;

const LegendItem = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
`;

const TIERS: Tier[] = ['high', 'medium', 'low', 'conflict', 'verified'];

export function TierLegend() {
  return (
    <LegendRow>
      {TIERS.map((tier) => (
        <LegendItem key={tier}>
          {/* Decorative here: the words beside it already say which tier this is. */}
          <Mark data-tier={tier} aria-hidden="true">
            {theme.tier[tier].mark}
          </Mark>
          {theme.tier[tier].label}
        </LegendItem>
      ))}
    </LegendRow>
  );
}
