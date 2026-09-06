import { Square } from 'lucide-react';
import styled from 'styled-components';

import { Surface } from '../../a2ui/Surface';
import { SurfaceBoundary } from '../../a2ui/SurfaceBoundary';
import { stageLabel, type Citation, type LiveAnswer } from '../answerStream';
import { CitationList } from './CitationList';
import { Prose } from './Prose';
import { StreamHeader } from './StreamHeader';

/**
 * One assistant turn, whether it is arriving now or was loaded from history.
 *
 * Both are a `LiveAnswer` by the time they reach here (`answerFromMessage` adapts the
 * persisted shape), so there is one rendering path and no chance of a streamed answer and
 * a reloaded one looking different.
 *
 * The order inside the card is the order the server sends things, and that is not a
 * coincidence: visual first, then prose, then citations. A card that
 * appeared after the prose had already been written would push the text a person was
 * reading down the page.
 */

const Block = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
`;

const Card = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.lg};
  padding: ${({ theme }) => theme.space.lg};

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  box-shadow: ${({ theme }) => theme.shadow.card};

  /* A card carrying a generated visual is the loudest thing in the thread; it earns a
     little more lift than a plain textual answer. */
  &[data-visual='true'] {
    box-shadow: ${({ theme }) => theme.shadow.raised};
  }
`;

/**
 * Space held for a visual the server has said is coming but has not sent yet.
 *
 * Held rather than left to collapse, because the alternative is prose that starts at the
 * top of the card and is shoved down a moment later. The window is short — the visual is
 * one message, sent complete — and this is what makes it invisible.
 */
const VisualPlaceholder = styled.div`
  height: 168px;
  background: ${({ theme }) => theme.color.paperSunken};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

const Notice = styled.p`
  font-size: 13px;
  line-height: 1.55;
  color: ${({ theme }) => theme.tier.conflict.color};
`;

const Footer = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.md};
`;

const StopButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;

  font-family: inherit;
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: color ${({ theme }) => theme.motion.quick};

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }
`;

const StoppedNote = styled.p`
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

export interface AnswerBlockProps {
  answer: LiveAnswer;
  /** True only for the turn currently being written. */
  streaming?: boolean;
  activeCitation?: number | null;
  onOpenCitation?: (citation: Citation) => void;
  onOpenRecord?: (recordId: string) => void;
  onStop?: () => void;
  canStop?: boolean;
}

export function AnswerBlock({
  answer,
  streaming = false,
  activeCitation,
  onOpenCitation,
  onOpenRecord,
  onStop,
  canStop = false,
}: AnswerBlockProps) {
  const byNumber = new Map(answer.citations.map((citation) => [citation.n, citation]));
  const showHeader = answer.sources.length > 0 || streaming;

  return (
    <Block>
      {showHeader && (
        <StreamHeader
          label={stageLabel(answer)}
          sources={answer.sources}
          live={streaming}
        />
      )}

      <Card data-visual={answer.visual !== null}>
        {/*
          The boundary is keyed per message: a fresh one per answer, rather than a
          boundary that has to work out when its own error has gone stale.
        */}
        {answer.visual && (
          <SurfaceBoundary key={answer.messageId} messages={answer.visual.surface}>
            <Surface messages={answer.visual.surface} onOpenRecord={onOpenRecord} />
          </SurfaceBoundary>
        )}
        {!answer.visual && answer.awaitingVisual && streaming && (
          <VisualPlaceholder aria-hidden="true" />
        )}

        {answer.text && (
          <div>
            <Prose
              text={answer.text}
              streaming={streaming && answer.stage === 'answering'}
              activeCitation={activeCitation}
              onCitationClick={(n) => {
                const citation = byNumber.get(n);
                if (citation) onOpenCitation?.(citation);
              }}
            />
          </div>
        )}

        {answer.error && <Notice role="alert">{answer.error}</Notice>}

        <CitationList
          citations={answer.citations}
          activeCitation={activeCitation}
          onOpen={onOpenCitation}
        />

        {/*
          Requirement FR-30: a stopped answer keeps what arrived and says it was stopped.
          Silently keeping a half-sentence would read as the model trailing off.
        */}
        {answer.stage === 'stopped' && (
          <StoppedNote>Stopped. What had been written is kept.</StoppedNote>
        )}

        {streaming && canStop && (
          <Footer>
            <StopButton type="button" onClick={onStop}>
              <Square size={11} aria-hidden="true" />
              Stop
            </StopButton>
          </Footer>
        )}
      </Card>
    </Block>
  );
}
