import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup);

/*
 * jsdom implements no 2D canvas context, and its `getContext` shouts about that once per
 * call through the virtual console. `ParticleText` already treats a missing context as
 * "this environment cannot draw" and renders only its accessible text, which is exactly
 * what these tests assert on. Returning null quietly says the same thing without burying
 * real failures under a wall of notices.
 */
HTMLCanvasElement.prototype.getContext = (() => null) as HTMLCanvasElement['getContext'];

/*
 * jsdom implements no `ResizeObserver`. Components that size themselves against their own
 * box — `Spiral`, `ParticleText` — construct one, and in jsdom it would throw before their
 * markup was ever asserted. A stub that observes nothing is honest here: jsdom has no
 * layout to report anyway, so a real implementation would only ever fire with zeroes.
 */
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;
