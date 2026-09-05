import styled from 'styled-components';

import type { Citation } from '../answerStream';

/**
 * The footnotes under an answer. Requirement FR-22.
 *
 * Each one names the document, where in it, and quotes the passage — so the citation is
 * checkable at a glance without opening anything, and opens the viewer with that exact
 * region highlighted when it is not. Product principle 4: every value on screen traces to
 * a highlighted region of its source, and this is that promise for prose.
 */

const List = styled.div`
  display: flex;
  flex-direction: column;
  border-top: 1px solid ${({ theme }) => theme.color.line};
`;

const Entry = styled.button`
  appearance: none;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.xs};
  padding: ${({ theme }) => theme.space.md} 0;

  font-family: inherit;
  text-align: left;
  background: none;
  border: 0;
  border-bottom: 1px solid ${({ theme }) => theme.color.line};
  cursor: pointer;

  &:last-child {
    border-bottom: 0;
  }

  &:hover,
  &[data-active='true'] {
    /* Reaches the card's padding, so the row highlights edge to edge rather than
       floating inside it. */
    box-shadow:
      inset 12px 0 0 ${({ theme }) => theme.color.paperSunken},
      inset -12px 0 0 ${({ theme }) => theme.color.paperSunken};
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

const Heading = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.space.sm};
  font-size: 13px;
  color: ${({ theme }) => theme.color.ink};
`;

const Number = styled.span`
  padding: 0 3px;
  font-size: 11px;
  line-height: 1.4;
  border: 1px solid ${({ theme }) => theme.color.ink};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

const Filename = styled.span`
  font-weight: 500;
`;

const Locator = styled.span`
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Excerpt = styled.span`
  font-size: 12px;
  line-height: 1.45;
  color: ${({ theme }) => theme.color.inkMuted};
`;

/**
 * Where in the document, written for a person.
 *
 * A digest citation has no page — it resolves through the extracted values' provenance
 * rather than through page text (`server/app/chat/citations.py`) — so it says so instead
 * of claiming a page it does not have.
 */
function locatorText(citation: Citation): string {
  if (citation.page_index === null || citation.page_index === undefined) {
    return '— extracted values';
  }
  return `— p. ${citation.page_index + 1}`;
}

export interface CitationListProps {
  citations: Citation[];
  activeCitation?: number | null;
  onOpen?: (citation: Citation) => void;
}

export function CitationList({ citations, activeCitation, onOpen }: CitationListProps) {
  if (citations.length === 0) return null;

  return (
    <List>
      {[...citations]
        // The stream delivers these in the order the model cited them, which is usually
        // ascending but is not promised to be. The list is a numbered reference.
        .sort((left, right) => left.n - right.n)
        .map((citation) => (
          <Entry
            key={citation.n}
            type="button"
            data-active={activeCitation === citation.n}
            onClick={() => onOpen?.(citation)}
          >
            <Heading>
              <Number aria-hidden="true">[{citation.n}]</Number>
              <Filename>{citation.filename}</Filename>
              <Locator>{locatorText(citation)}</Locator>
            </Heading>
            {citation.excerpt && <Excerpt>“…{citation.excerpt}…”</Excerpt>}
          </Entry>
        ))}
    </List>
  );
}
