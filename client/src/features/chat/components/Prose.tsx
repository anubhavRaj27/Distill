import { Fragment } from 'react';
import styled from 'styled-components';

/**
 * The answer's text, with its citation markers turned into buttons as they arrive.
 *
 * The server rewrites the model's `[^chunk:<uuid>]` markers into `[^n]` before the token
 * leaves it, and guarantees the matching `citation` event has already been sent
 * (decision D45). So a marker found here always has a citation behind it, and this
 * component never has to render an unresolved footnote and then rewrite it — which is the
 * flicker that ordering rule exists to prevent.
 *
 * Deliberately not a Markdown renderer. The answers are prose with footnotes; adding a
 * Markdown pipeline would mean sanitising model-authored HTML on the one surface where the
 * model's output reaches the page directly, for the sake of formatting nothing asks for.
 */

const Paragraph = styled.p`
  font-size: 14px;
  line-height: 1.7;
  color: ${({ theme }) => theme.color.ink};
  text-wrap: pretty;

  & + & {
    margin-top: ${({ theme }) => theme.space.md};
  }
`;

/**
 * A footnote marker.
 *
 * Sized and aligned to sit in the line without pushing it apart: a superscript number that
 * changed the leading would make the whole paragraph twitch as each marker streamed in.
 */
const Marker = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  margin: 0 1px;
  padding: 0 3px;

  font-family: inherit;
  font-size: 11px;
  line-height: 1.4;
  vertical-align: baseline;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.ink};
  border-radius: ${({ theme }) => theme.radius.sm};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover {
    background: ${({ theme }) => theme.color.inkSurface};
    color: ${({ theme }) => theme.color.onInk};
  }

  &[data-active='true'] {
    background: ${({ theme }) => theme.color.inkSurface};
    color: ${({ theme }) => theme.color.onInk};
  }
`;

/**
 * The cursor, while tokens are still arriving.
 *
 * A block that sits at the end of the text rather than a spinner beside it: the point of
 * a token stream is that the answer is visibly being written, and the caret is where the
 * writing is happening.
 */
const Caret = styled.span`
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: ${({ theme }) => theme.color.ink};
  animation: blink 1.1s steps(2, start) infinite;

  @keyframes blink {
    50% {
      opacity: 0;
    }
  }
`;

const MARKER = /\[\^(\d+)\]/g;

export interface ProseProps {
  text: string;
  /** Which footnote is currently open in the viewer, if any. */
  activeCitation?: number | null;
  onCitationClick?: (n: number) => void;
  /** Draws the caret at the end. False once the answer has settled. */
  streaming?: boolean;
}

export function Prose({
  text,
  activeCitation,
  onCitationClick,
  streaming = false,
}: ProseProps) {
  // A blank line is a paragraph break; a single newline is not, because the model wraps
  // its own lines and honouring those would break paragraphs in arbitrary places.
  const paragraphs = text.split(/\n{2,}/);

  return (
    <>
      {paragraphs.map((paragraph, index) => (
        <Paragraph key={index}>
          {renderMarkers(paragraph, activeCitation ?? null, onCitationClick)}
          {streaming && index === paragraphs.length - 1 && <Caret aria-hidden="true" />}
        </Paragraph>
      ))}
    </>
  );
}

function renderMarkers(
  paragraph: string,
  active: number | null,
  onClick?: (n: number) => void,
) {
  const pieces: React.ReactNode[] = [];
  let cursor = 0;

  // `matchAll` rather than a stateful `exec` loop: the regex is module-level, and a shared
  // `lastIndex` across two paragraphs rendering in the same tick would skip markers.
  for (const match of paragraph.matchAll(MARKER)) {
    const at = match.index;
    if (at > cursor) pieces.push(paragraph.slice(cursor, at));

    const n = Number(match[1]);
    pieces.push(
      <Marker
        key={`${at}-${n}`}
        type="button"
        data-active={active === n}
        onClick={() => onClick?.(n)}
        aria-label={`Show source ${n}`}
      >
        [{n}]
      </Marker>,
    );
    cursor = at + match[0].length;
  }

  if (cursor < paragraph.length) pieces.push(paragraph.slice(cursor));

  return pieces.map((piece, index) => <Fragment key={index}>{piece}</Fragment>);
}
