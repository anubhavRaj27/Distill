import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router';
import styled from 'styled-components';

import { api, authHeader, toFailure } from '../../api/client';
import { AppHeader } from '../../app/AppHeader';
import { useRenameWorkspace } from '../../app/useRenameWorkspace';
import { logger } from '../../lib/logger';
import { consumeTokenFromFragment, recallToken } from '../../lib/workspace-token';
import { ProcessingStrip } from '../processing/ProcessingStrip';
import { useDocumentProgress } from '../processing/useDocumentProgress';
import { SourceViewer, type SourceTarget } from '../viewer/SourceViewer';
import { answerFromMessage, type Citation } from './answerStream';
import { AnswerBlock } from './components/AnswerBlock';
import { Composer } from './components/Composer';
import { Suggestions } from './components/Suggestions';
import { UserBubble } from './components/UserBubble';
import { useConversation } from './useConversation';
import { useSuggestions } from './useSuggestions';

/**
 * Screen 2 of three: Chat. Routes `/w/{id}` and `/w/{id}/chat`. Requirements section 3.2.
 *
 * The product's main screen. Everything the pipeline did exists so that a question typed
 * here can be answered from the documents and checked against them, which is why this
 * screen holds the two things the others do not: the streamed answer, and the viewer that
 * every citation opens.
 *
 * It is deliberately usable while documents are still being read. The upload screen hands
 * over as soon as bytes have arrived (decision D36), so the processing strip narrates the
 * rest here rather than a spinner standing between a person and the documents that are
 * already indexed.
 */

const Page = styled.div`
  height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

const Split = styled.div`
  flex: 1;
  min-height: 0;
  display: flex;
`;

/** The thread scrolls; the composer inside it is sticky, so it never leaves the view. */
const Thread = styled.main`
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: ${({ theme }) => theme.space.xxl} ${({ theme }) => theme.space.xl} 0;
`;

const Column = styled.div`
  width: 100%;
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.xl};
  /* Pushes the conversation to the bottom of a short thread, so the first question is
     near the composer rather than stranded at the top of an empty screen. */
  margin-top: auto;
`;

const Opening = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.lg};
  padding-bottom: ${({ theme }) => theme.space.md};
`;

const Greeting = styled.h1`
  font-family: ${({ theme }) => theme.font.display};
  font-weight: 400;
  font-size: 26px;
  line-height: 1.2;
  color: ${({ theme }) => theme.color.ink};
`;

const Note = styled.p`
  font-size: 13px;
  line-height: 1.6;
  color: ${({ theme }) => theme.color.inkMuted};
  max-width: ${({ theme }) => theme.measure.narrow};
`;

const Failure = styled.p`
  font-size: 13px;
  color: ${({ theme }) => theme.tier.conflict.color};
`;

export function ChatScreen() {
  const { workspaceId = '' } = useParams();

  // A shared link carries the token in its fragment; it is moved into storage and stripped
  // from the address bar before anything renders (decision D21).
  const [token] = useState(
    () => consumeTokenFromFragment(workspaceId) ?? recallToken(workspaceId),
  );

  useEffect(() => {
    document.title = 'Distill · chat';
  }, []);

  const overview = useQuery({
    queryKey: ['workspace', workspaceId],
    enabled: Boolean(token),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/workspaces/{workspace_id}', {
        params: { path: { workspace_id: workspaceId }, header: authHeader(token!) },
      });
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },
  });

  const documents = overview.data?.documents ?? [];
  const progress = useDocumentProgress(
    workspaceId,
    token,
    documents.map((document) => ({
      id: document.id,
      filename: document.filename,
      status: document.status,
    })),
  );

  /*
   * The overview is a snapshot, and on this screen it is routinely taken before the
   * documents exist: arriving here straight from an upload (decision D36) means it was
   * fetched while the workspace was still empty, so the header said "0 documents" over a
   * conversation about one. Refetching when the live stream reports another document
   * settled is what keeps the chrome honest, and it is a refetch rather than an
   * invalidation.
   */
  const settledCount = progress.filter(
    (document) => document.status === 'done' || document.status === 'failed',
  ).length;
  const refetchedAt = useRef(0);
  const refetchOverview = overview.refetch;
  useEffect(() => {
    if (settledCount <= refetchedAt.current) return;
    refetchedAt.current = settledCount;
    void refetchOverview();
  }, [settledCount, refetchOverview]);

  const rename = useRenameWorkspace(workspaceId, token);
  const conversation = useConversation(workspaceId, token);
  const anyReady = progress.some((document) => document.status === 'done');
  const suggestions = useSuggestions(workspaceId, token, anyReady);

  const [viewing, setViewing] = useState<SourceTarget | null>(null);
  // The question being typed lives here rather than in the composer, because a suggested
  // question is written into it from outside.
  const [draft, setDraft] = useState('');

  const openCitation = useCallback((citation: Citation) => {
    setViewing({
      documentId: citation.document_id,
      filename: citation.filename,
      pageIndex: citation.page_index,
      boxes: citation.boxes,
      excerpt: citation.excerpt,
      n: citation.n,
    });
  }, []);

  const ask = useCallback(
    (question: string) => {
      logger.event('chat.asked', { length: question.length });
      conversation.ask(question);
    },
    [conversation],
  );

  /*
   * Follow the tail of the conversation as it grows.
   *
   * Only when the person is already near the bottom: yanking the view down while someone
   * is reading an earlier answer is the single most irritating thing a streaming interface
   * can do, and the token stream would do it several times a second.
   */
  const thread = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const element = thread.current;
    if (!element) return;

    const onScroll = () => {
      const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
      pinned.current = distance < 120;
    };
    element.addEventListener('scroll', onScroll, { passive: true });
    return () => element.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const element = thread.current;
    if (!element || !pinned.current) return;
    element.scrollTop = element.scrollHeight;
  }, [conversation.messages.length, conversation.live?.text, conversation.live?.stage]);

  if (!token) {
    return (
      <Page>
        <AppHeader active="chat" />
        <Split>
          <Thread>
            <Column>
              <Note role="alert">
                This workspace needs its access token, and this browser does not have it.
                Open the link you were given in full, including everything after the{' '}
                <code>#</code>.
              </Note>
            </Column>
          </Thread>
        </Split>
      </Page>
    );
  }

  const empty = conversation.messages.length === 0 && conversation.live === null;

  return (
    <Page>
      <AppHeader
        active="chat"
        workspace={{
          id: workspaceId,
          label: overview.data?.label ?? 'Untitled workspace',
          documentCount: documents.length,
        }}
        onAddDocuments={() => logger.event('upload.start', { from: 'workspace-header' })}
        onRename={(label) => rename.mutate(label)}
      />

      <Split>
        <Thread ref={thread}>
          <Column>
            <ProcessingStrip documents={progress} />

            {empty && (
              <Opening>
                <Greeting>Ask about your documents.</Greeting>
                <Note>
                  Answers are drawn from what is actually in the files, and every figure and
                  claim carries a citation you can open to the page it came from.
                </Note>
                {/* A suggestion fills the box rather than sending, so it can be edited
                    into the question actually wanted. */}
                <Suggestions questions={suggestions.data ?? []} onPick={setDraft} />
              </Opening>
            )}

            {conversation.messages.map((message) =>
              message.role === 'user' ? (
                <UserBubble key={message.id} text={message.content} />
              ) : (
                <AnswerBlock
                  key={message.id}
                  answer={answerFromMessage(message)}
                  activeCitation={viewing?.n ?? null}
                  onOpenCitation={openCitation}
                />
              ),
            )}

            {conversation.live && (
              <AnswerBlock
                answer={conversation.live}
                streaming
                activeCitation={viewing?.n ?? null}
                onOpenCitation={openCitation}
                onStop={conversation.stop}
                canStop={conversation.canStop}
              />
            )}

            {conversation.error && (
              <Failure role="alert">
                {conversation.error.message}
                {conversation.error.correlationId
                  ? ` (${conversation.error.correlationId})`
                  : ''}
              </Failure>
            )}

            <Composer
              value={draft}
              onChange={setDraft}
              onAsk={ask}
              // One question at a time. Asking again mid-answer would abandon a stream
              // that the server is still paying to generate.
              disabled={conversation.isAsking || conversation.live !== null}
            />
          </Column>
        </Thread>

        {viewing && (
          <SourceViewer
            workspaceId={workspaceId}
            token={token}
            target={viewing}
            onClose={() => setViewing(null)}
          />
        )}
      </Split>
    </Page>
  );
}
