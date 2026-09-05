import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import styled from 'styled-components';

import { usePrefersReducedMotion } from './usePrefersReducedMotion';

/**
 * Slides arranged along a slowly turning helix: each one swings out from the centre,
 * rotates to face you at the front of the curve, and falls away blurred at the back.
 *
 * Adapted from componentry.dev's "spiral 3D slider", which is a `three` scene: one textured
 * plane per slide, a shader for the depth blur, and `@react-three/fiber` around it. That is
 * about 600 kB of dependency, and it can only draw images.
 *
 * This is the same geometry — the placement maths below is the upstream `useFrame` body,
 * angle step and easing constants included — expressed as CSS 3D transforms on ordinary DOM
 * nodes. Two things follow from that, and both matter more here than the shader did:
 *
 * - **A slide is real markup.** On the upload screen a slide is a document: a filename, a
 *   format, a status, a thumbnail of the actual file. A WebGL texture cannot be any of
 *   those things without first being rendered to an image.
 * - **It works everywhere.** No WebGL context to lose, no error boundary, no fallback for
 *   a machine that will not give the tab a GPU.
 *
 * Per-frame writes go straight to `style` on nodes held in a ref. Driving 12 transforms
 * through React state at 60fps would be 720 renders a second to move some pixels.
 */

/** Radians of turn between neighbouring slides. Upstream's constant. */
const ANGLE_STEP = 0.78;
/** How far a slide yaws as it swings around, in radians at the extremes. */
const YAW = 1.12;
/** Blur and fade reach their maximum at this fraction of the ring. */
const FALLOFF = 0.43;

/** A thin ring reads as a fan rather than a spiral, so short lists are repeated. */
const MIN_SLIDES = 10;

export interface SpiralSlide {
  /** Stable across re-renders. Repeats of the same slide get a suffix internally. */
  key: string;
  node: ReactNode;
}

export interface SpiralProps {
  slides: SpiralSlide[];
  /** Height of the stage, in pixels. Slides are clipped to it. */
  height?: number;
  /**
   * Horizontal reach of the helix, in pixels. Treated as a maximum: the helix narrows on a
   * narrow stage rather than being clipped down the sides.
   */
  radius?: number;
  /** Vertical distance between neighbours, in pixels. */
  verticalGap?: number;
  cardWidth?: number;
  /** Width divided by height. Below 1 for portrait, which is what paper is. */
  cardAspectRatio?: number;
  /** Slides per second. */
  speed?: number;
  /** Maximum blur on the slides furthest away, in pixels. */
  blurStrength?: number;
  /** Named for assistive technology, which gets the list below rather than the stage. */
  ariaLabel: string;
}

const Stage = styled.div`
  position: relative;
  width: 100%;
  overflow: hidden;
  perspective: 1200px;
`;

const Ring = styled.div`
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
`;

const Slot = styled.div`
  position: absolute;
  top: 50%;
  left: 50%;
  transform-style: preserve-3d;
  will-change: transform, opacity, filter;
`;

/**
 * The static rendering, for a visitor who has asked for less motion.
 *
 * Not the moving spiral with its animation switched off — that would leave a stack of
 * cards at odd angles with no explanation of why. A plain overlapping fan of the first few
 * slides says the same thing and holds still.
 */
const StaticFan = styled.div`
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
`;

const FanSlot = styled.div`
  flex-shrink: 0;
`;

/** Screen readers get the caller's own list instead; the stage is decoration. */
const Description = styled.div`
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
`;

/** Fold an index onto the ring, so slide 11 of 12 sits just *before* slide 0, not after. */
function wrap(value: number, length: number): number {
  const positive = ((value % length) + length) % length;
  return positive > length / 2 ? positive - length : positive;
}

export function Spiral({
  slides,
  height = 460,
  radius = 265,
  verticalGap = 46,
  cardWidth = 150,
  cardAspectRatio = 3 / 4,
  speed = 0.34,
  blurStrength = 2.4,
  ariaLabel,
}: SpiralProps) {
  const reducedMotion = usePrefersReducedMotion();
  const slotRefs = useRef<(HTMLDivElement | null)[]>([]);
  const stageRef = useRef<HTMLDivElement>(null);

  const cardHeight = Math.round(cardWidth / cardAspectRatio);

  // Repeat a short list until the ring is full. Fewer than ten slides leaves visible gaps
  // where the helix should close on itself.
  const ring = useMemo(() => {
    if (slides.length === 0) return [];
    const total = Math.max(slides.length, MIN_SLIDES);
    return Array.from({ length: total }, (_, index) => {
      const slide = slides[index % slides.length]!;
      return { key: `${slide.key}#${index}`, node: slide.node };
    });
  }, [slides]);

  useEffect(() => {
    if (reducedMotion || ring.length === 0) return;

    const stage = stageRef.current;
    if (!stage) return;

    const count = ring.length;
    let frame = 0;
    let progress = 0;
    let last = performance.now();

    /*
     * The helix is sized against the stage, not against a constant. `radius` is the widest
     * it may ever be; on a narrow stage it narrows so the outermost card still lands inside
     * the clip. Measured once per resize rather than per frame — `clientWidth` forces
     * layout, and doing that 60 times a second to read a number that rarely changes is how
     * a decorative animation ends up costing more than the upload it is decorating.
     */
    let reach = radius;
    const measure = () => {
      const usable = Math.max(stage.clientWidth / 2 - cardWidth * 0.42, 40);
      reach = Math.min(radius, usable);
    };
    measure();

    const place = () => {
      for (let index = 0; index < count; index += 1) {
        const slot = slotRefs.current[index];
        if (!slot) continue;

        const position = wrap(index - progress, count);
        const angle = position * ANGLE_STEP;
        // 1 at the front of the curve, 0 at the back. Drives scale, so the near slide is
        // the large one.
        const depth = (Math.cos(angle) + 1) / 2;
        const distance = Math.min(Math.abs(position) / (count * FALLOFF), 1);

        const x = Math.sin(angle) * reach;
        const y = -position * verticalGap;
        const z = Math.cos(angle) * 60;
        const scale = 0.74 + depth * 0.26;
        const blur = Math.pow(distance, 1.28) * blurStrength;

        slot.style.transform =
          `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, ${z.toFixed(2)}px)` +
          ` rotateY(${((-Math.sin(angle) * YAW * 180) / Math.PI).toFixed(2)}deg)` +
          ` scale(${scale.toFixed(3)})`;
        // Fading with distance is what lets the helix run past the top and bottom edges
        // without the clip looking like a cut.
        slot.style.opacity = (1 - distance * 0.92).toFixed(3);
        slot.style.filter = blur > 0.08 ? `blur(${blur.toFixed(2)}px)` : '';
      }
    };

    const tick = (now: number) => {
      // Clamped: a tab returning from the background hands over one enormous delta, which
      // would otherwise teleport the spiral several turns forward.
      const delta = Math.min((now - last) / 1000, 0.05);
      last = now;
      progress += speed * delta;
      place();
      frame = requestAnimationFrame(tick);
    };

    // One placement before the first frame, so nothing is ever painted stacked at centre.
    place();
    frame = requestAnimationFrame(tick);

    /*
     * A backgrounded tab throttles `requestAnimationFrame` rather than stopping it, and
     * this screen is exactly the one people switch away from while they wait. Stopping
     * outright, and resetting the clock on return, costs nothing and spends nothing.
     */
    const onVisibility = () => {
      cancelAnimationFrame(frame);
      if (document.hidden) return;
      last = performance.now();
      frame = requestAnimationFrame(tick);
    };
    document.addEventListener('visibilitychange', onVisibility);

    const observer = new ResizeObserver(() => {
      measure();
      place();
    });
    observer.observe(stage);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [reducedMotion, ring.length, radius, cardWidth, verticalGap, speed, blurStrength]);

  if (slides.length === 0) return null;

  if (reducedMotion) {
    return (
      <StaticFan style={{ height }} aria-hidden="true">
        {slides.slice(0, 5).map((slide, index, shown) => (
          <FanSlot
            key={slide.key}
            style={{
              width: cardWidth,
              height: cardHeight,
              marginLeft: index === 0 ? 0 : -cardWidth * 0.36,
              transform: `rotate(${(index - (shown.length - 1) / 2) * 4}deg)`,
              zIndex: index,
            }}
          >
            {slide.node}
          </FanSlot>
        ))}
      </StaticFan>
    );
  }

  return (
    <Stage ref={stageRef} style={{ height }} role="presentation">
      <Ring aria-hidden="true">
        {ring.map((slide, index) => (
          <Slot
            key={slide.key}
            ref={(node) => {
              slotRefs.current[index] = node;
            }}
            style={{
              width: cardWidth,
              height: cardHeight,
              marginLeft: -cardWidth / 2,
              marginTop: -cardHeight / 2,
            }}
          >
            {slide.node}
          </Slot>
        ))}
      </Ring>
      <Description>{ariaLabel}</Description>
    </Stage>
  );
}
