import { AlertCircle, Check, Loader } from 'lucide-react';
import styled from 'styled-components';

import { STAGE_WORDS } from './stageWords';
import type { DocumentProgress } from './useDocumentProgress';

/**
 * What the server is still doing to the documents. Requirement FR-04.
 *
 * Compact and at the top, and it disappears the moment everything has settled — a
 * permanent status bar on a screen whose subject is a conversation would be furniture.
 * While it is there it is specific: a stage per document, and the sub-state underneath
 * when the server has one ("scanned image detected, running text recognition"), because
 * the thing a person actually wants to know during a long wait is whether it is stuck.
 *
 * Failures are the exception to disappearing. A document that failed keeps its row, with
 * the reason the server wrote for a person to read, since the answers from here on are
 * missing whatever was in it.
 */

const Strip = styled.section`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.sm};
  padding: ${({ theme }) => theme.space.md} ${({ theme }) => theme.space.lg};

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
`;

const Summary = styled.p`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};

  svg[data-spinning='true'] {
    animation: spin 1.4s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
`;

const Rows = styled.ul`
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

const Row = styled.li`
  display: flex;
  align-items: baseline;
  gap: ${({ theme }) => theme.space.sm};
  font-size: 12px;
  line-height: 1.5;
  color: ${({ theme }) => theme.color.inkMuted};

  &[data-failed='true'] {
    color: ${({ theme }) => theme.tier.conflict.color};
  }
`;

const Name = styled.span`
  min-width: 0;
  max-width: 260px;
  color: ${({ theme }) => theme.color.ink};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  [data-failed='true'] > & {
    color: inherit;
  }
`;

const Stage = styled.span`
  font-variant: small-caps;
  letter-spacing: 0.02em;
`;

export interface ProcessingStripProps {
  documents: DocumentProgress[];
}

export function ProcessingStrip({ documents }: ProcessingStripProps) {
  const working = documents.filter(
    (document) => document.status !== 'done' && document.status !== 'failed',
  );
  const failed = documents.filter((document) => document.status === 'failed');

  // Nothing in flight and nothing broken: the strip has no business being on screen.
  if (working.length === 0 && failed.length === 0) return null;

  const ready = documents.filter((document) => document.status === 'done').length;

  return (
    <Strip aria-live="polite">
      {working.length > 0 && (
        <Summary>
          <Loader size={13} data-spinning="true" aria-hidden="true" />
          Reading {working.length} of {documents.length}{' '}
          {documents.length === 1 ? 'document' : 'documents'} — {ready} ready so far. You
          can ask about the ones that are.
        </Summary>
      )}

      <Rows>
        {[...working, ...failed].map((document) => (
          <Row key={document.documentId} data-failed={document.status === 'failed'}>
            {document.status === 'failed' ? (
              <AlertCircle size={12} aria-hidden="true" />
            ) : document.status === 'done' ? (
              <Check size={12} aria-hidden="true" />
            ) : null}
            <Name title={document.filename}>{document.filename}</Name>
            <Stage>{STAGE_WORDS[document.status] ?? document.status}</Stage>
            {document.failureReason && <span>— {document.failureReason}</span>}
            {!document.failureReason && document.stageDetail && (
              <span>— {document.stageDetail}</span>
            )}
          </Row>
        ))}
      </Rows>
    </Strip>
  );
}
