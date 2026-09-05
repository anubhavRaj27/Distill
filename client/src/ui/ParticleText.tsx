import { useEffect, useRef } from 'react';
import styled from 'styled-components';

import { usePrefersReducedMotion } from './usePrefersReducedMotion';

/**
 * Type drawn as particles that scatter away from the cursor and spring back into the
 * letterforms.
 *
 * Adapted from componentry.dev's "cursor-driven particle typography", which ships as a
 * shadcn registry component: Tailwind classes, a `cn` helper, and a `"use client"` banner,
 * none of which exist here. The physics — a repulsion field inside a 120px radius, a spring
 * pulling each particle back to the pixel it came from, friction at 0.85 — is kept as
 * written. Everything around it is this project's: styled-components, theme tokens, and the
 * two things below that the original does not do.
 *
 * **It stops.** The original runs `requestAnimationFrame` forever, including on a page
 * nobody is touching. Here the loop halts once the pointer has left and every particle has
 * settled, and a pointer entering the canvas starts it again. The original's random jitter
 * near origin was dropped to make that possible; at 1.5px it was not visible anyway, and a
 * mark that holds still until you touch it suits a product about settling data.
 *
 * **It respects `prefers-reduced-motion`.** No canvas is created at all; the same word
 * renders as ordinary type. GlobalStyle's reduced-motion block cannot reach a canvas, so a
 * component that animates in one has to honour the preference itself.
 *
 * The word is always in the DOM as real text — the canvas is decorative and hidden from
 * assistive technology — so it is selectable, searchable, and read aloud correctly.
 */

const INTERACTION_RADIUS = 120;
const FRICTION = 0.85;
/** Below this displacement and velocity, with the pointer away, there is nothing to draw. */
const SETTLED_EPSILON = 0.05;
/** Parked far off-canvas: no particle is ever within the interaction radius of it. */
const POINTER_AWAY = -1000;

interface Particle {
  x: number;
  y: number;
  originX: number;
  originY: number;
  vx: number;
  vy: number;
}

export interface ParticleTextProps {
  /** The word to draw. Also what a screen reader and a text search see. */
  text: string;
  /** Cap on the drawn size. Shrinks to fit a narrow container. */
  fontSize?: number;
  fontFamily?: string;
  /** Radius of one particle, in CSS pixels. */
  particleSize?: number;
  /** Sampling step through the rasterised word. Lower means denser, minimum 1. */
  particleDensity?: number;
  /** How hard the cursor pushes. */
  dispersionStrength?: number;
  /** Spring constant pulling a particle home. */
  returnSpeed?: number;
  /** Defaults to the inherited text colour. */
  color?: string;
  /** Height of the canvas band, in CSS pixels. */
  height?: number;
  className?: string;
}

const Root = styled.div`
  position: relative;
  width: 100%;
  /* The canvas swallows scroll gestures on a touch device without this. */
  touch-action: none;

  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }
`;

/**
 * The word itself, present for assistive technology and for selection.
 *
 * Clipped rather than `display: none`, which would take it out of the accessibility tree
 * along with the visual — leaving a heading with no name at all.
 */
const VisuallyHidden = styled.span`
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

/** The reduced-motion rendering: the same word, as type. */
const StaticText = styled.span<{ $size: number; $family: string; $color?: string }>`
  display: block;
  width: 100%;
  font-family: ${({ $family }) => $family};
  /*
   * The canvas path shrinks the word to fit by measuring it. Type cannot measure itself,
   * so it shrinks against the viewport instead — without this a display size chosen for a
   * desktop hero runs off the side of a phone.
   */
  font-size: min(${({ $size }) => $size}px, 20vw);
  font-weight: 700;
  line-height: 1;
  text-align: center;
  color: ${({ $color, theme }) => $color ?? theme.color.ink};
`;

export function ParticleText({
  text,
  fontSize = 120,
  fontFamily = 'Inter, sans-serif',
  particleSize = 1.5,
  particleDensity = 3,
  dispersionStrength = 15,
  returnSpeed = 0.08,
  color,
  height = 200,
  className,
}: ParticleTextProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (reducedMotion) return;

    const canvas = canvasRef.current;
    const root = rootRef.current;
    if (!canvas || !root) return;

    // `willReadFrequently` because the whole technique is one `getImageData` per layout.
    // jsdom implements no 2D context at all, so this has to be allowed to fail quietly.
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d', { willReadFrequently: true });
    } catch {
      ctx = null;
    }
    if (!ctx) return;
    const context = ctx;

    let particles: Particle[] = [];
    let frame = 0;
    let running = false;
    let width = 0;
    let height = 0;
    let pointerX = POINTER_AWAY;
    let pointerY = POINTER_AWAY;

    /** Rasterise the word, then keep one particle per opaque pixel on a grid. */
    const build = () => {
      width = root.clientWidth;
      height = root.clientHeight;
      if (width === 0 || height === 0) return;

      const dpr = window.devicePixelRatio || 1;
      // Assigning width resets the transform, so the scale below never compounds.
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.scale(dpr, dpr);

      const ink = color || window.getComputedStyle(root).color || '#000000';

      context.clearRect(0, 0, width, height);
      context.fillStyle = ink;
      context.textAlign = 'center';
      context.textBaseline = 'middle';

      /*
       * Shrink to fit by measuring, not by a fixed fraction of the container.
       * The original component capped the size at 15% of the width, which is really a
       * guess about how many letters the word has: it overflows a long one and starves a
       * short one of size for no reason. Measuring costs one extra `measureText` and is
       * correct for any word in any face.
       */
      context.font = `bold ${fontSize}px ${fontFamily}`;
      const measured = context.measureText(text).width;
      const budget = width * 0.86;
      const drawnSize =
        measured > budget ? Math.floor(fontSize * (budget / measured)) : fontSize;
      if (drawnSize !== fontSize) context.font = `bold ${drawnSize}px ${fontFamily}`;

      context.fillText(text, width / 2, height / 2);

      const raster = context.getImageData(0, 0, canvas.width, canvas.height);
      const step = Math.max(1, Math.floor(particleDensity * dpr));

      particles = [];
      for (let y = 0; y < raster.height; y += step) {
        for (let x = 0; x < raster.width; x += step) {
          const alpha = raster.data[(y * raster.width + x) * 4 + 3] ?? 0;
          if (alpha <= 128) continue;

          const originX = x / dpr;
          const originY = y / dpr;
          particles.push({
            // A little scatter at birth, so the word assembles rather than appearing.
            x: originX + (Math.random() - 0.5) * 10,
            y: originY + (Math.random() - 0.5) * 10,
            originX,
            originY,
            vx: (Math.random() - 0.5) * 5,
            vy: (Math.random() - 0.5) * 5,
          });
        }
      }
    };

    /** Advance one particle. Returns true while it still has somewhere to be. */
    const advance = (particle: Particle): boolean => {
      const dx = pointerX - particle.x;
      const dy = pointerY - particle.y;
      const distance = Math.hypot(dx, dy);

      if (distance < INTERACTION_RADIUS && distance > 0) {
        const force = (INTERACTION_RADIUS - distance) / INTERACTION_RADIUS;
        particle.vx -= (dx / distance) * force * dispersionStrength;
        particle.vy -= (dy / distance) * force * dispersionStrength;
      }

      particle.vx += (particle.originX - particle.x) * returnSpeed;
      particle.vy += (particle.originY - particle.y) * returnSpeed;
      particle.vx *= FRICTION;
      particle.vy *= FRICTION;

      particle.x += particle.vx;
      particle.y += particle.vy;

      return (
        Math.abs(particle.vx) > SETTLED_EPSILON ||
        Math.abs(particle.vy) > SETTLED_EPSILON ||
        Math.abs(particle.x - particle.originX) > SETTLED_EPSILON ||
        Math.abs(particle.y - particle.originY) > SETTLED_EPSILON
      );
    };

    const draw = () => {
      context.clearRect(0, 0, width, height);
      let moving = false;

      for (const particle of particles) {
        if (advance(particle)) moving = true;
        context.beginPath();
        context.arc(particle.x, particle.y, particleSize, 0, Math.PI * 2);
        context.fill();
      }

      // Nothing left to animate and nobody pushing: hold the frame and stop burning one
      // per refresh. `wake` restarts on the next pointer move.
      if (!moving && pointerX === POINTER_AWAY) {
        running = false;
        return;
      }
      frame = requestAnimationFrame(draw);
    };

    const wake = () => {
      if (running) return;
      running = true;
      frame = requestAnimationFrame(draw);
    };

    const trackPointer = (clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect();
      pointerX = clientX - rect.left;
      pointerY = clientY - rect.top;
      wake();
    };

    const onMouseMove = (event: MouseEvent) => trackPointer(event.clientX, event.clientY);

    const onTouch = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (touch) trackPointer(touch.clientX, touch.clientY);
    };

    const onPointerLeave = () => {
      pointerX = POINTER_AWAY;
      pointerY = POINTER_AWAY;
      // Still running: the particles have to spring home before the loop may stop.
      wake();
    };

    // Fonts load after first paint, and measuring the word before its face is ready
    // rasterises the fallback. Rebuilding on `fonts.ready` costs one extra raster.
    const rebuild = () => {
      build();
      wake();
    };

    rebuild();
    document.fonts?.ready.then(rebuild).catch(() => {});

    const observer = new ResizeObserver(rebuild);
    observer.observe(root);

    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseleave', onPointerLeave);
    canvas.addEventListener('touchstart', onTouch, { passive: true });
    canvas.addEventListener('touchmove', onTouch, { passive: true });
    canvas.addEventListener('touchend', onPointerLeave);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.removeEventListener('mousemove', onMouseMove);
      canvas.removeEventListener('mouseleave', onPointerLeave);
      canvas.removeEventListener('touchstart', onTouch);
      canvas.removeEventListener('touchmove', onTouch);
      canvas.removeEventListener('touchend', onPointerLeave);
    };
  }, [
    text,
    fontSize,
    fontFamily,
    particleSize,
    particleDensity,
    dispersionStrength,
    returnSpeed,
    color,
    reducedMotion,
  ]);

  if (reducedMotion) {
    return (
      <StaticText
        className={className}
        $size={fontSize}
        $family={fontFamily}
        $color={color}
      >
        {text}
      </StaticText>
    );
  }

  return (
    <Root ref={rootRef} className={className} style={{ height, color }}>
      <VisuallyHidden>{text}</VisuallyHidden>
      <canvas ref={canvasRef} aria-hidden="true" />
    </Root>
  );
}
