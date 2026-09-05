import { BookOpen, FileText } from 'lucide-react';
import styled from 'styled-components';

import { distinctDocuments, type SourceRef } from '../answerStream';

/**
 * What the answer read, above the answer.
 *
 * This is the first thing on screen after a question is asked, and it is the reason the
 * wait does not feel like a spinner: the stage line says what is happening, and the chips
 * name the documents being read as soon as retrieval has picked them — before a single
 * token of prose exists. The `sources` event is sent early precisely so this can happen
 * (`server/app/chat/events.py`).
 */

const Line = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.space.sm};

  font-size: 12px;
  line-height: 1.35;
  color: ${({ theme }) => theme.color.inkMuted};

  svg {
    flex-shrink: 0;
  }
`;

const Label = styled.span`
  /* Stops the chips from jumping left as the wording lengthens mid-stream. */
  white-space: nowrap;
`;

const Chip = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  max-width: 220px;

  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
`;

export interface StreamHeaderProps {
  label: string;
  sources: SourceRef[];
  /**
   * Announced to assistive technology while the answer is being written. Off once it has
   * settled, so a rendered history does not re-announce every stage line on mount.
   */
  live?: boolean;
}

export function StreamHeader({ label, sources, live = false }: StreamHeaderProps) {
  const documents = distinctDocuments(sources);

  return (
    <Line role={live ? 'status' : undefined} aria-live={live ? 'polite' : undefined}>
      <BookOpen size={14} aria-hidden="true" />
      <Label>{label}</Label>

      {documents.map((document) => (
        <Chip key={document.document_id} title={document.filename}>
          <FileText size={12} aria-hidden="true" />
          <span>{document.filename}</span>
        </Chip>
      ))}
    </Line>
  );
}
