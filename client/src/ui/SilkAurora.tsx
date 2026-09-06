import { useEffect, useRef, useState } from 'react';
import styled, { useTheme } from 'styled-components';

import { usePrefersReducedMotion } from './usePrefersReducedMotion';

/**
 * A slow aurora, rendered by a fragment shader, behind the first-run screen.
 *
 * Adapted from componentry.dev's "Silk Aurora", the same source as `Spiral` — but where
 * that one was reimplemented in CSS to shed 600 kB of `three`, this one is kept as WebGL,
 * because the original already is: it is plain WebGL 1, one full-screen triangle strip and
 * one fragment shader, with no npm dependency of any kind. There is nothing to save by
 * rewriting it, and nothing in CSS that draws flowing ribbons of light.
 *
 * Three things were changed, and all three are the reasons this is a port rather than a
 * copy.
 *
 * **It is a background, not a hero.** Upstream ships a full-height section that renders its
 * own headline, subtitle and description, and expects the page to be arranged around it.
 * All of that is gone. What is left fills whatever positioned box it is dropped into and
 * paints, plus the scrim that keeps the words on top of it legible.
 *
 * **Its colours come from the theme.** Upstream hard-codes a near-black base with champagne
 * and mint. Here every colour is a token, so the aurora follows the palette
 * instead of pasting a dark rectangle into a paper-coloured page.
 *
 * **It can subtract.** That is the substantive change, and it is what makes a light mode
 * possible at all — see `u_polarity` in the shader below.
 */

const VERTEX_SHADER = `
attribute vec2 position;

void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

/*
 * The shader, kept close to the original so it can still be diffed against it. The noise,
 * fbm and ribbon functions and the constants that shape them are upstream's; the light
 * `mix` and everything to do with `u_polarity` are not.
 */
const FRAGMENT_SHADER = `
precision highp float;

uniform vec2 u_res;
uniform vec2 u_mouse;
uniform float u_time;
uniform float u_speed;
uniform float u_intensity;
uniform float u_grain;
uniform float u_vignette;
uniform float u_mouseInfluence;
/*
 * 1.0 on a dark ground, 0.0 on a light one.
 *
 * The original is purely additive: it starts near black and adds light, which is the only
 * thing that works on a dark page and the only thing that cannot work on a pale one, where
 * every ribbon saturates to white and the whole panel turns into a smear. On paper the
 * physical model is the other one — ink taken out of white — so at 0.0 each ribbon
 * subtracts its own complement instead of adding its colour. Removing the blue from cream
 * leaves gold; removing the red leaves sage. Same geometry, opposite arithmetic.
 */
uniform float u_polarity;
uniform vec3 u_base;
uniform vec3 u_mid;
uniform vec3 u_sheen;
uniform vec3 u_accent;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(41.93, 289.17))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);

  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));

  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
  float value = 0.0;
  float amp = 0.5;
  mat2 rot = mat2(0.82, 0.57, -0.57, 0.82);

  for (int i = 0; i < 5; i++) {
    value += amp * noise(p);
    p = rot * p * 2.03;
    amp *= 0.5;
  }

  return value;
}

float ribbon(vec2 p, float offset, float width, float softness) {
  float y = p.y + sin(p.x * 1.8 + offset) * 0.18;
  y += sin(p.x * 4.2 - offset * 0.7) * 0.045;
  return smoothstep(width + softness, width, abs(y));
}

/** Adds light on a dark ground, removes ink on a pale one. See u_polarity. */
vec3 veil(vec3 col, vec3 tint, float amount) {
  vec3 lit = tint * amount;
  vec3 inked = (vec3(1.0) - tint) * amount;
  return col + mix(-inked, lit, u_polarity);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  float aspect = u_res.x / max(u_res.y, 1.0);
  vec2 p = (uv - 0.5) * vec2(aspect, 1.0);

  vec2 mouse = (u_mouse - 0.5) * vec2(aspect, 1.0);
  float t = u_time * 0.12 * u_speed;
  float pointerFalloff = smoothstep(0.72, 0.0, length(p - mouse));
  p += (mouse - p) * pointerFalloff * 0.05 * u_mouseInfluence;

  vec2 silk = p;
  silk.x += fbm(p * 1.6 + vec2(t * 0.8, -t * 0.35)) * 0.16;
  silk.y += fbm(p * 2.2 + vec2(-t * 0.25, t * 0.7)) * 0.10;

  float veilA = ribbon(silk + vec2(-0.18, 0.08), t * 2.1, 0.055, 0.22);
  float veilB = ribbon(silk * vec2(0.86, 1.18) + vec2(0.2, -0.14), -t * 2.8 + 1.7, 0.038, 0.18);
  float veilC = ribbon(silk * vec2(1.18, 0.9) + vec2(-0.08, 0.24), t * 1.4 - 2.1, 0.03, 0.16);

  float atmosphere = fbm(p * 1.35 + vec2(t * 0.22, -t * 0.1));
  float pearlescent = pow(max(0.0, sin((p.x - p.y) * 7.5 + atmosphere * 4.0 - t * 2.5)), 5.0);

  vec3 col = u_base;
  col = mix(col, u_mid, smoothstep(-0.45, 0.75, p.y + atmosphere * 0.75));
  col = veil(col, u_accent, veilA * 0.72 * u_intensity);
  col = veil(col, u_sheen, veilB * 0.64 * u_intensity);
  col = veil(col, mix(u_sheen, u_accent, 0.35), veilC * 0.42 * u_intensity);
  col = veil(col, u_sheen, pearlescent * 0.075 * u_intensity);
  col = veil(col, u_sheen, pointerFalloff * 0.08 * u_mouseInfluence);

  /*
   * Upstream's glint — a sparse, fast white sparkle — is cut. It is a luxury-hero flourish,
   * and on a 640 by 220 panel that a person is about to drop files into it reads as noise
   * on the screen rather than as light.
   */

  float vignette = smoothstep(1.25, 0.22, length(p));
  col *= mix(1.0 - u_vignette * 0.42, 1.04, vignette);

  float grain = (hash(gl_FragCoord.xy + t * 90.0) - 0.5) * 0.08 * u_grain;
  col += grain;

  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
`;

function hexToRgb01(hex: string): [number, number, number] {
  const value = hex.replace('#', '');
  return [
    Number.parseInt(value.slice(0, 2), 16) / 255,
    Number.parseInt(value.slice(2, 4), 16) / 255,
    Number.parseInt(value.slice(4, 6), 16) / 255,
  ];
}

const Root = styled.div`
  position: absolute;
  inset: 0;
  overflow: hidden;
  border-radius: inherit;

  /*
   * It is decoration. It must never take a click meant for the screen underneath, and it
   * must never be read out: what it says is nothing.
   */
  pointer-events: none;

  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }
`;

/**
 * The scrim that protects the words: a band of the page's own colour down the middle, in
 * pixels rather than percentages.
 *
 * The 4.5:1 contrast minimum is a requirement, not an aspiration, and text over a moving
 * shader cannot be measured. So the middle of the screen — the column the wordmark, the
 * standfirst and the drop zone sit in — is held at the page's own colour, and the aurora is
 * left to the margins, where nothing has to be read. What it looks like is ribbons passing
 * behind the content; what it is, is a promise that the contrast in the middle is the
 * contrast the tests assert.
 *
 * The content is a centred column that runs nearly the full height and is never wider than
 * `measure.prose`, so the shape that protects it is a vertical band, not an ellipse. Being
 * a fixed width is the point: an ellipse sized in percentages is a constant fraction of the
 * window, so it protects the column at one width and either strangles the aurora or exposes
 * the text at every other. A band of a fixed number of pixels covers the same column at
 * every window size, and on a window too narrow to have margins it covers everything — which
 * is the right answer, since a window that small has no room for decoration anyway.
 *
 * Everything outside it is margin, and the aurora is free to be as strong there as it likes.
 */
const CentreScrim = styled.div`
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    90deg,
    transparent 0,
    var(--paper) calc(50% - 420px),
    var(--paper) calc(50% + 420px),
    transparent 100%
  );

  /*
   * And a gap through the band, where the drop zone is.
   *
   * The band exists for text with nothing behind it: the standfirst above, the sample link
   * and the format list below. The drop zone is not that. It is a panel with a translucent
   * surface of its own, so holding flat paper behind it would put the one element a person
   * is actually looking at in the only place on the page where the aurora cannot be seen.
   * The band stands down across that stripe and the zone becomes a window into it instead.
   *
   * These stops are percentages of the viewport while the zone is a fixed 220px in a centred
   * column, so the two line up approximately and drift apart at a very tall or very short
   * window. That is what the long fades are for: drift is invisible through a fade and would
   * read as a seam across the page through a hard edge.
   */
  mask-image: linear-gradient(
    to bottom,
    #000 0%,
    #000 38%,
    transparent 50%,
    transparent 70%,
    #000 82%,
    #000 100%
  );
`;

/**
 * A flat wash over the whole thing, to take the hardest edge off the margins.
 *
 * Much lighter on paper than on ink. On a dark ground the aurora is added light and wants
 * damping; on a pale one it is ink removed from cream, which is already the gentler of the
 * two operations, and veiling it further was most of why the light palette read as barely
 * there.
 */
const Veil = styled.div`
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: var(--paper);
  opacity: ${({ theme }) => (theme.mode === 'dark' ? 0.18 : 0.06)};
`;

export interface SilkAuroraProps {
  /** Global animation speed multiplier. */
  speed?: number;
  /** Strength of the ribbons and the sheen. Defaults per palette; see below. */
  intensity?: number;
  /** Amount of fine shader grain. */
  grain?: number;
  /** Edge darkening strength. Defaults per palette; see below. */
  vignette?: number;
  /** Whether the ribbons lean towards the pointer. */
  interactive?: boolean;
  className?: string;
}

/**
 * Two of the defaults depend on which way round the page is, because adding light and
 * removing ink are not symmetric operations.
 *
 * **Intensity.** Adding light to near-black has a long way to travel before anything is
 * blown out. Subtracting ink from cream does not: the same numbers that read as a gentle
 * glow on ink read as a stain on paper. So the light palette gets a little over half.
 *
 * **Vignette.** Multiplying darkens in both directions, but on a dark ground it disappears
 * into the ground and on a pale one it draws a grey border and turns a panel into a
 * photograph of a panel.
 */
const PER_MODE = {
  light: { intensity: 1, vignette: 0.35 },
  dark: { intensity: 0.9, vignette: 0.7 },
} as const;

export function SilkAurora({
  speed = 1,
  intensity,
  grain = 0.45,
  vignette,
  interactive = true,
  className,
}: SilkAuroraProps) {
  const theme = useTheme();
  const reducedMotion = usePrefersReducedMotion();
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [unavailable, setUnavailable] = useState(false);

  const { aurora } = theme.color;
  const polarity = theme.mode === 'dark' ? 1 : 0;
  const defaults = PER_MODE[theme.mode];
  const resolvedIntensity = intensity ?? defaults.intensity;
  const resolvedVignette = vignette ?? defaults.vignette;

  useEffect(() => {
    const root = rootRef.current;
    const canvas = canvasRef.current;
    if (!root || !canvas) return;

    /*
     * A pointer position in this element's own coordinates, tracked on the window because
     * the canvas itself takes no pointer events. Written to a ref rather than to state: it
     * changes at the pointer's sample rate and is read once per frame.
     */
    const pointer = { x: 0.5, y: 0.5 };
    const target = { x: 0.5, y: 0.5 };

    const onPointerMove = (event: PointerEvent) => {
      if (!interactive) return;
      const rect = root.getBoundingClientRect();
      target.x = (event.clientX - rect.left) / rect.width;
      target.y = 1 - (event.clientY - rect.top) / rect.height;
    };
    window.addEventListener('pointermove', onPointerMove, { passive: true });

    const gl = (() => {
      try {
        return canvas.getContext('webgl', { antialias: false, alpha: false });
      } catch {
        return null;
      }
    })();

    if (!gl) {
      setUnavailable(true);
      return () => window.removeEventListener('pointermove', onPointerMove);
    }

    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    };

    const vertex = compile(gl.VERTEX_SHADER, VERTEX_SHADER);
    const fragment = compile(gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    const program = vertex && fragment ? gl.createProgram() : null;

    const giveUp = () => {
      if (vertex) gl.deleteShader(vertex);
      if (fragment) gl.deleteShader(fragment);
      if (program) gl.deleteProgram(program);
      setUnavailable(true);
      window.removeEventListener('pointermove', onPointerMove);
    };

    if (!vertex || !fragment || !program) {
      giveUp();
      return;
    }

    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      giveUp();
      return;
    }
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const position = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const at = (name: string) => gl.getUniformLocation(program, name);
    const uRes = at('u_res');
    const uMouse = at('u_mouse');
    const uTime = at('u_time');
    const uSpeed = at('u_speed');
    const uIntensity = at('u_intensity');
    const uGrain = at('u_grain');
    const uVignette = at('u_vignette');
    const uMouseInfluence = at('u_mouseInfluence');
    const uPolarity = at('u_polarity');

    const setColor = (name: string, hex: string) => {
      const [r, g, b] = hexToRgb01(hex);
      gl.uniform3f(at(name), r, g, b);
    };
    setColor('u_base', aurora.base);
    setColor('u_mid', aurora.mid);
    setColor('u_sheen', aurora.sheen);
    setColor('u_accent', aurora.accent);
    gl.uniform1f(uPolarity, polarity);

    /*
     * Device pixel ratio is capped at 1.25 rather than the usual 2.
     *
     * This shader runs three fbm calls of five octaves each, per pixel, per frame, and it
     * now covers a whole screen rather than a 640 by 220 panel — on a retina display the
     * uncapped version is four times the pixels for a picture made entirely of soft
     * gradients, which have no edge a retina pixel could resolve. The one thing that does
     * carry detail is the grain, and 1.25 keeps enough of it to read as tooth rather than
     * as blocks.
     */
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.25);
      const { width, height } = root.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uRes, canvas.width, canvas.height);
    };
    resize();

    let frame = 0;
    const start = performance.now();

    const draw = (now: number) => {
      pointer.x += (target.x - pointer.x) * 0.045;
      pointer.y += (target.y - pointer.y) * 0.045;

      /*
       * Under reduced motion the clock is frozen at a fixed offset rather than the shader
       * being skipped. The panel keeps a still aurora — a texture, which is what somebody
       * who asked for less motion should get — instead of a flat rectangle.
       */
      const elapsed = reducedMotion ? 8 : (now - start) / 1000;

      gl.uniform2f(uMouse, pointer.x, pointer.y);
      gl.uniform1f(uTime, elapsed);
      gl.uniform1f(uSpeed, reducedMotion ? 0 : speed);
      gl.uniform1f(uIntensity, resolvedIntensity);
      gl.uniform1f(uGrain, grain);
      gl.uniform1f(uVignette, resolvedVignette);
      gl.uniform1f(uMouseInfluence, interactive && !reducedMotion ? 1 : 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

      // One frame is enough when nothing moves; the loop stops rather than redrawing it.
      if (reducedMotion) return;
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);

    /*
     * The redraw after a resize is not redundant under reduced motion, it is the only thing
     * keeping the panel from going black. Assigning `canvas.width` clears the drawing
     * buffer, and with the loop stopped after its single frame there is nothing to put the
     * picture back.
     */
    const observer = new ResizeObserver(() => {
      resize();
      if (!reducedMotion) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    });
    observer.observe(root);

    /*
     * A background tab still schedules frames in some browsers, and this one costs real GPU
     * time. Nothing is being conveyed while the tab is hidden, so the loop stops.
     */
    const onVisibility = () => {
      cancelAnimationFrame(frame);
      if (!document.hidden) frame = requestAnimationFrame(draw);
    };
    document.addEventListener('visibilitychange', onVisibility);

    /*
     * A lost context is normal, not exceptional: switching GPUs, waking from sleep, or the
     * browser reclaiming contexts from other tabs will all do it. Preventing the default
     * and standing down leaves the drop zone's own surface showing, which is a background
     * that looks deliberate rather than a hole.
     */
    const onLost = (event: Event) => {
      event.preventDefault();
      cancelAnimationFrame(frame);
      setUnavailable(true);
    };
    canvas.addEventListener('webglcontextlost', onLost);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('visibilitychange', onVisibility);
      canvas.removeEventListener('webglcontextlost', onLost);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
    };
  }, [
    aurora.accent,
    aurora.base,
    aurora.mid,
    aurora.sheen,
    grain,
    interactive,
    polarity,
    reducedMotion,
    resolvedIntensity,
    resolvedVignette,
    speed,
  ]);

  /*
   * No WebGL, or a context that went away: render nothing at all.
   *
   * Upstream shows a notice reading "Interactive WebGL content is unavailable", which is
   * right for a hero whose absence would leave an empty screen and wrong for this. Here the
   * whole element is decoration behind a drop zone that is complete without it, and the
   * surface underneath is already the colour it should be. Announcing the absence of a
   * decoration is telling somebody about a problem they do not have.
   */
  if (unavailable) return null;

  return (
    <Root ref={rootRef} className={className} aria-hidden="true">
      <canvas ref={canvasRef} />
      <Veil />
      <CentreScrim />
    </Root>
  );
}
