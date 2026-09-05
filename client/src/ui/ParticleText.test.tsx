import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Providers } from '../app/Providers';
import { makeQueryClient } from '../app/queryClient';
import { ParticleText } from './ParticleText';

/**
 * Two things have to hold whatever the rendering path: the word is real text in the
 * document, and a visitor who asked for less motion gets no animation at all. The physics
 * itself is not asserted — it is a canvas jsdom cannot draw, and pinning particle
 * positions would test arithmetic rather than behaviour.
 */

function renderText() {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <h1>
        <ParticleText text="Distill" />
      </h1>
    </Providers>,
  );
}

/** jsdom ships no `matchMedia`; the component treats its absence as "no preference". */
function stubMotionPreference(reduce: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: reduce && query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ParticleText', () => {
  it('names its heading with real text, not just pixels on a canvas', () => {
    const { container } = renderText();

    expect(screen.getByRole('heading', { name: 'Distill' })).toBeInTheDocument();
    // Decorative: the word is already in the accessibility tree above it.
    expect(container.querySelector('canvas')).toHaveAttribute('aria-hidden', 'true');
  });

  it('draws nothing at all when the visitor has asked for less motion', () => {
    stubMotionPreference(true);
    const { container } = renderText();

    expect(screen.getByRole('heading', { name: 'Distill' })).toBeInTheDocument();
    expect(container.querySelector('canvas')).toBeNull();
  });

  it('animates when no motion preference is expressed', () => {
    stubMotionPreference(false);
    const { container } = renderText();

    expect(container.querySelector('canvas')).not.toBeNull();
  });
});
