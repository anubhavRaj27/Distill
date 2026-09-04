import styled, { keyframes } from 'styled-components';

/**
 * The argument of the product, made before a person has uploaded anything.
 *
 * Four documents that plainly disagree with one another — different stock, different
 * layouts, one of them a spreadsheet — narrow through a funnel into a single ruled table
 * with one settled, verified value in it. Mess in, clarity out. The empty state has to
 * teach in about thirty seconds without anyone reading documentation (product principle 5
 * in requirements.md), and a picture does that faster than a paragraph.
 *
 * Decorative: it is hidden from assistive technology, and the sentence above it in
 * `FirstRunScreen` carries the same meaning in words.
 */

/*
 * A CSS `transform` on an SVG element overrides its `transform` *attribute* outright
 * rather than composing with it, and `animation-fill-mode: both` makes that permanent.
 * Animating a positioned group directly therefore throws away its position. Every animated
 * group here is a wrapper that carries no attribute transform of its own; placement lives
 * on a child.
 */
const settle = keyframes`
  from { opacity: 0; transform: translateY(-6px); }
  to   { opacity: 1; transform: translateY(0); }
`;

const arrive = keyframes`
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
`;

const Figure = styled.figure`
  margin: 0;
  width: 100%;
  /*
   * Sized so the whole screen — headline, illustration, drop zone, and both buttons —
   * clears the fold on a 1280×800 laptop. The picture is the argument, but the two ways in
   * are the point, and a person should not have to scroll to find them.
   */
  max-width: 400px;

  svg {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
  }

  /*
   * Restrained motion with a reason: the documents land first, the funnel draws, then the
   * table settles underneath them. It reads as the pipeline running once. The global
   * reduced-motion guard in GlobalStyle collapses all of it to nothing.
   */
  [data-settle] {
    animation: ${settle} ${({ theme }) => theme.motion.settle} both;
  }
  [data-settle='1'] {
    animation-delay: 0ms;
  }
  [data-settle='2'] {
    animation-delay: 70ms;
  }
  [data-settle='3'] {
    animation-delay: 140ms;
  }
  [data-settle='4'] {
    animation-delay: 210ms;
  }

  [data-arrive] {
    animation: ${arrive} ${({ theme }) => theme.motion.settle} 320ms both;
  }
`;

/** One of the loose input documents. */
function Sheet({
  x,
  y,
  rotate,
  fill,
  stroke,
  children,
  order,
}: {
  x: number;
  y: number;
  rotate: number;
  fill: string;
  stroke: string;
  order: number;
  children: React.ReactNode;
}) {
  return (
    <g data-settle={order}>
      <g transform={`translate(${x} ${y}) rotate(${rotate} 42 50)`}>
        <rect width="84" height="100" rx="3" fill={fill} stroke={stroke} strokeWidth="1" />
        {children}
      </g>
    </g>
  );
}

/** A line of text on a document, drawn rather than written. */
function Rule({
  y,
  width,
  fill,
  x = 10,
}: {
  y: number;
  width: number;
  fill: string;
  x?: number;
}) {
  return <rect x={x} y={y} width={width} height="5" rx="2.5" fill={fill} />;
}

export function DistillationMark() {
  return (
    <Figure aria-hidden="true">
      <svg viewBox="0 0 520 296" role="presentation" focusable="false">
        {/* An invoice. */}
        <Sheet
          x={36}
          y={14}
          rotate={-6}
          order={1}
          fill="var(--paper-raised)"
          stroke="var(--line)"
        >
          <Rule y={16} width={64} fill="var(--stock-mid)" />
          <Rule y={28} width={42} fill="var(--stock-mid)" />
          <Rule y={80} width={64} fill="var(--stock-light)" />
        </Sheet>

        {/* A scan: heavier stock, denser text, no clean structure. */}
        <Sheet
          x={140}
          y={6}
          rotate={4}
          order={2}
          fill="var(--paper-sunken)"
          stroke="var(--stock-heavy)"
        >
          <Rule y={16} width={64} fill="var(--stock-heavy)" />
          <Rule y={28} width={50} fill="var(--stock-heavy)" />
          <Rule y={40} width={34} fill="var(--stock-mid)" />
        </Sheet>

        {/* A spreadsheet: already tabular, and still not the same table as the others. */}
        <Sheet
          x={256}
          y={18}
          rotate={-3}
          order={3}
          fill="var(--paper-raised)"
          stroke="var(--line)"
        >
          {[0, 1, 2].map((row) =>
            [0, 1, 2].map((col) => (
              <rect
                key={`${row}-${col}`}
                x={10 + col * 22}
                y={16 + row * 22}
                width="20"
                height="20"
                fill={row === 1 ? 'var(--stock-lightest)' : 'var(--stock-light)'}
              />
            )),
          )}
        </Sheet>

        {/* A statement. */}
        <Sheet
          x={368}
          y={10}
          rotate={7}
          order={4}
          fill="var(--paper-raised)"
          stroke="var(--line)"
        >
          <Rule y={16} width={64} fill="var(--stock-mid)" />
          <Rule y={28} width={64} fill="var(--stock-mid)" />
          <Rule y={40} width={42} fill="var(--stock-light)" />
          <Rule y={52} width={30} fill="var(--stock-light)" />
        </Sheet>

        {/* The funnel. Two guides, narrowing onto the corners of the table. */}
        <g data-arrive>
          <line
            x1="128"
            y1="152"
            x2="188"
            y2="204"
            stroke="var(--stock-heavy)"
            strokeWidth="1"
          />
          <line
            x1="392"
            y1="152"
            x2="332"
            y2="204"
            stroke="var(--stock-heavy)"
            strokeWidth="1"
          />
        </g>

        {/* One table. Ruled, aligned, and carrying a value someone has verified. */}
        <g data-arrive>
          <g transform="translate(174 208)">
            <rect
              width="172"
              height="82"
              rx="3"
              fill="var(--paper-raised)"
              stroke="var(--ink)"
              strokeWidth="1.5"
            />
            {[0, 1, 2].map((row) =>
              [0, 1, 2].map((col) => (
                <rect
                  key={`${row}-${col}`}
                  x={5 + col * 54}
                  y={5 + row * 24}
                  width="54"
                  height="24"
                  fill="none"
                  stroke="var(--line)"
                  strokeWidth="1"
                />
              )),
            )}
            {/* One value, landed and verified: the smallest possible promise of the
                product, made before anything has been uploaded. */}
            <circle cx="148" cy="17" r="4" fill="var(--tier-verified)" />
          </g>
        </g>
      </svg>
    </Figure>
  );
}
