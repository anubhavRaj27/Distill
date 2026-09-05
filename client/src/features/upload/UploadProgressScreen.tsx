import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import styled from 'styled-components';

import { api, authHeader, toFailure } from '../../api/client';
import { AppHeader } from '../../app/AppHeader';
import {
  ACCEPT_ATTRIBUTE,
  formatBytes,
  sortIntake,
  type RejectedFile,
} from '../../lib/files';
import { logger } from '../../lib/logger';
import { makeTasks, runBatch, type UploadTask } from '../../lib/upload';
import { consumeTokenFromFragment, recallToken } from '../../lib/workspace-token';
import { Spiral } from '../../ui/Spiral';
import { useDocumentProgress } from '../processing/useDocumentProgress';
import { SourceViewer, type SourceTarget } from '../viewer/SourceViewer';
import { DocumentCard } from './components/DocumentCard';
import { RejectionNotice } from './components/RejectionNotice';
import { UploadRow } from './components/UploadRow';
import { DocumentLibrary, type LibraryDocument } from './DocumentLibrary';
import { usePendingUploads } from './pendingUploads';
import { useDeleteDocument } from './useDeleteDocument';

/**
 * Screen 1: the workspace's documents, and the files going up. Route `/w/{id}/upload`.
 *
 * **The library** is every document in this workspace, what became of it, and a way to open
 * or delete it. It is what this screen is for once a workspace exists, and it was missing:
 * arriving here with ten documents indexed produced the sentence "this browser is not
 * uploading anything right now" and nothing else, which answers a question nobody asked.
 * See decision D71.
 *
 * **The upload** is bytes leaving this browser, a transient state drawn above the library
 * while it lasts. The screen still holds the person here until that finishes, because there
 * is genuinely nothing to do with a document the server has not received yet. "Ready" there
 * means received, not indexed.
 *
 * Processing (parse, extract, index) deliberately does **not** hold anyone here. It runs on
 * the server and streams `document.status` events, which the processing strip renders on
 * Chat and Data (requirement FR-04). Making people watch a 60-second pipeline finish before
 * they may ask a question would trade a real capability for a progress bar.
 *
 * A reload mid-flight loses the browser's handles to those files, so the screen falls back
 * to showing what the server already has rather than pretending it can resume.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

/**
 * The viewer is a panel beside the content, not below it, so this screen splits horizontally
 * under the header exactly as Chat does. Without it the `aside` becomes the next row of a
 * column layout and opens somewhere off the bottom of the page.
 */
const Split = styled.div`
  flex: 1;
  min-height: 0;
  display: flex;
`;

const Main = styled.main`
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: ${({ theme }) => theme.space.page};
`;

const Library = styled.section`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
  width: 100%;
  max-width: 880px;
  margin-top: ${({ theme }) => theme.space.xl};
`;

const LibraryHeading = styled.h2`
  margin: 0;
  font-family: ${({ theme }) => theme.font.body};
  font-size: 13px;
  font-weight: 500;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Headline = styled.h1`
  font-family: ${({ theme }) => theme.font.display};
  font-weight: 400;
  font-size: 34px;
  line-height: 1.15;
  color: ${({ theme }) => theme.color.ink};
  text-align: center;
`;

const Panel = styled.ul`
  width: 100%;
  margin: 0;
  padding: 0;
  list-style: none;

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-top: 0;
  border-radius: 0 0 ${({ theme }) => theme.radius.md} ${({ theme }) => theme.radius.md};
  overflow: hidden;
`;

/**
 * The spiral of the person's own documents, turning while their bytes are in flight.
 *
 * A progress bar is honest and boring, and this wait is the first sustained look anyone
 * gets at the product. The cards are the actual files being sent — real thumbnails for
 * images, drawn sheets for the rest — so the animation is about *their* pile rather than
 * being decoration bolted on to pass the time. Decision D58.
 */
const Carousel = styled.div`
  width: 100%;
  max-width: 880px;
  margin-top: ${({ theme }) => theme.space.lg};
`;

/** The one number that answers "how much longer". Sits directly under the spiral. */
const Summary = styled.div`
  width: 100%;
  max-width: 420px;
  margin-top: ${({ theme }) => theme.space.lg};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.sm};
  text-align: center;
`;

const SummaryLine = styled.p`
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};

  strong {
    font-weight: 600;
    color: ${({ theme }) => theme.color.ink};
  }
`;

const TotalBar = styled.progress`
  appearance: none;
  display: block;
  width: 100%;
  height: 3px;
  border: 0;
  border-radius: ${({ theme }) => theme.radius.pill};

  &::-webkit-progress-bar {
    background: ${({ theme }) => theme.color.line};
    border-radius: ${({ theme }) => theme.radius.pill};
  }
  &::-webkit-progress-value {
    background: ${({ theme }) => theme.color.ink};
    border-radius: ${({ theme }) => theme.radius.pill};
    transition: inline-size ${({ theme }) => theme.motion.quick};
  }
  &::-moz-progress-bar {
    background: ${({ theme }) => theme.color.ink};
    border-radius: ${({ theme }) => theme.radius.pill};
  }
`;

/**
 * The per-file rows, folded away.
 *
 * They are the truth of what happened to each file and they cannot be cut — a failure has
 * to be readable, and the bars carry the accessible progress. But eight rows of near
 * identical bars is not what this wait should look like, so they sit behind a disclosure
 * that opens itself the moment anything goes wrong.
 */
const Details = styled.details`
  width: 100%;
  max-width: 880px;
  margin-top: ${({ theme }) => theme.space.xxl};
`;

const SummaryToggle = styled.summary`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: ${({ theme }) => theme.space.md};
  padding: 10px 16px;

  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  list-style: none;

  &::-webkit-details-marker {
    display: none;
  }

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }

  [open] > & {
    border-radius: ${({ theme }) => theme.radius.md} ${({ theme }) => theme.radius.md} 0 0;
  }

  &[data-failed='true'] {
    color: ${({ theme }) => theme.tier.conflict.color};
  }
`;

const Actions = styled.div`
  width: 100%;
  max-width: 880px;
  margin-top: ${({ theme }) => theme.space.xxl};
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: ${({ theme }) => theme.space.lg};
`;

const SecondaryButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;

  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.paperSunken};
  }
  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
`;

const ContinueButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
  padding: 10px 20px;

  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  color: ${({ theme }) => theme.color.onInk};
  background: ${({ theme }) => theme.color.inkSurface};
  border: 1px solid ${({ theme }) => theme.color.inkSurface};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.inkSurfaceHover};
  }
  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
`;

const Note = styled.p`
  width: 100%;
  max-width: 880px;
  margin-top: ${({ theme }) => theme.space.lg};
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const HiddenInput = styled.input`
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

/** One shared empty array, so a miss does not allocate a new reference each render. */
const NO_FILES: File[] = [];

export function UploadProgressScreen() {
  const { workspaceId = '' } = useParams();
  const navigate = useNavigate();
  const addInput = useRef<HTMLInputElement>(null);

  const [token] = useState(
    () => consumeTokenFromFragment(workspaceId) ?? recallToken(workspaceId),
  );

  /*
   * Taken once, on mount. The store exists only to survive the navigation from screen 1.
   *
   * Each field is selected on its own and compared afterwards, rather than with a selector
   * that returns `state.workspaceId === id ? state.files : []`. That version allocates a
   * fresh array on every miss, so the store's snapshot never compares equal and React
   * re-renders until it gives up with "Maximum update depth exceeded". Selectors must
   * return something referentially stable.
   */
  const pendingWorkspaceId = usePendingUploads((state) => state.workspaceId);
  const pendingFiles = usePendingUploads((state) => state.files);
  const pendingRejected = usePendingUploads((state) => state.rejected);
  const mine = pendingWorkspaceId === workspaceId;
  const staged = mine ? pendingFiles : NO_FILES;
  const clearPending = usePendingUploads((state) => state.clear);
  const [tasks, setTasks] = useState<UploadTask[]>(() => makeTasks(staged));
  const [rejected, setRejected] = useState<RejectedFile[]>(() =>
    mine ? pendingRejected : [],
  );

  const patch = useCallback((key: string, change: Partial<UploadTask>) => {
    setTasks((current) =>
      current.map((task) => (task.key === key ? { ...task, ...change } : task)),
    );
  }, []);

  /** Start (or extend) the batch. Runs for files that have not been sent yet. */
  const send = useCallback(
    async (pending: UploadTask[]) => {
      if (!token || pending.length === 0) return;
      await runBatch({
        baseUrl: import.meta.env.VITE_API_URL ?? '',
        workspaceId,
        token,
        tasks: pending,
        onChange: patch,
      });
    },
    [patch, token, workspaceId],
  );

  const started = useRef(false);
  useEffect(() => {
    if (started.current || tasks.length === 0) return;
    started.current = true;
    clearPending();
    logger.event('upload.start', { files: tasks.length });
    void send(tasks);
    // `tasks` is the initial batch; later additions are sent by their own handler.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * What the server holds. Only consulted when this screen has no batch of its own — after
   * a reload, when the browser's file handles are gone.
   */
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

  const handleAdd = useCallback(
    (files: File[]) => {
      const { accepted, rejected: refused } = sortIntake(files);
      setRejected(refused);

      if (accepted.length === 0) return;
      const added = makeTasks(accepted).map((task) => ({
        ...task,
        key: `${task.key}-${Date.now()}`,
      }));
      setTasks((current) => [...current, ...added]);
      void send(added);
    },
    [send],
  );

  const { sending, failed, allSettled, arrived, sentBytes, totalBytes } = useMemo(() => {
    const isSending = tasks.some(
      (task) => task.phase === 'waiting' || task.phase === 'sending',
    );
    return {
      sending: isSending,
      failed: tasks.filter((task) => task.phase === 'failed').length,
      allSettled: tasks.length > 0 && !isSending,
      arrived: tasks.filter((task) => task.phase === 'ready').length,
      // A failed file's bytes are not counted as sent; a bar that fills to 100% while a
      // file is being reported as lost is the kind of small lie people notice.
      sentBytes: tasks.reduce(
        (total, task) => total + (task.phase === 'failed' ? 0 : task.sent),
        0,
      ),
      totalBytes: tasks.reduce((total, task) => total + task.file.size, 0),
    };
  }, [tasks]);

  /*
   * One card per file, in upload order. `Spiral` repeats them itself when there are too
   * few to close the ring, so a single document still turns rather than hanging there.
   */
  const slides = useMemo(
    () => tasks.map((task) => ({ key: task.key, node: <DocumentCard task={task} /> })),
    [tasks],
  );

  const documentCount =
    tasks.length > 0
      ? tasks.filter((task) => task.phase === 'ready').length
      : (overview.data?.documents?.length ?? 0);

  /*
   * Shut while things are going well, forced open by a failure. Held in state rather than
   * left to the browser so the second half is possible at all; the person can still shut
   * it again afterwards.
   */
  const [detailsOpen, setDetailsOpen] = useState(false);
  const handleToggle = useCallback((event: React.ToggleEvent<HTMLDetailsElement>) => {
    setDetailsOpen(event.currentTarget.open);
  }, []);

  useEffect(() => {
    if (failed > 0) setDetailsOpen(true);
  }, [failed]);

  /*
   * The workspace overview is cached under `['workspace', id]` with a stale time, and this
   * screen fetches it on mount — before its own files have arrived. Without this, Chat and
   * Data inherit that snapshot and report a workspace with no documents in it for the next
   * thirty seconds, having just watched the documents upload.
   *
   * Invalidating when the batch settles is the honest fix: this screen knows the workspace
   * changed, because it is what changed it.
   */
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!allSettled) return;
    void queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] });
  }, [allSettled, queryClient, workspaceId]);

  const goToChat = useCallback(() => {
    void navigate(`/w/${workspaceId}/chat`);
  }, [navigate, workspaceId]);

  /*
   * The library, and the live stages laid over it. Decision D71.
   *
   * The overview is the list of what exists; the event stream is what is happening to it.
   * The hook the processing strip uses is reused rather than a second subscriber written
   * here, so two views of one pipeline cannot disagree about a document's stage.
   */
  const stored = useMemo(() => overview.data?.documents ?? [], [overview.data]);
  const progress = useDocumentProgress(
    workspaceId,
    token,
    useMemo(
      () =>
        stored.map((document) => ({
          id: document.id,
          filename: document.filename,
          status: document.status,
        })),
      [stored],
    ),
  );

  const library = useMemo<LibraryDocument[]>(() => {
    const live = new Map(progress.map((entry) => [entry.documentId, entry]));
    return stored.map((document) => {
      const entry = live.get(document.id);
      return {
        ...document,
        liveStatus: entry?.status,
        liveStageDetail: entry?.stageDetail,
        liveFailureReason: entry?.failureReason,
      };
    });
  }, [progress, stored]);

  /*
   * A document reaching a terminal stage changes what the overview says about it — the page
   * count, the failure reason — and the overview is a snapshot taken before any of that
   * happened. Refetching when the number of settled documents changes keeps the rows honest
   * without polling: the stream says when there is something new to ask for.
   */
  const settledCount = library.filter((document) => {
    const status = document.liveStatus ?? document.status;
    return status === 'done' || status === 'failed';
  }).length;
  const refetchedAt = useRef(0);
  useEffect(() => {
    // Only when the number GROWS, and remembered in a ref rather than in state: the
    // refetch this triggers is what recomputes `settledCount`, so a condition that can be
    // met by its own result is a loop waiting to happen.
    if (settledCount <= refetchedAt.current) return;
    refetchedAt.current = settledCount;
    void queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] });
  }, [settledCount, queryClient, workspaceId]);

  const removal = useDeleteDocument(workspaceId, token);
  const [viewing, setViewing] = useState<SourceTarget | null>(null);

  const openDocument = useCallback((document: LibraryDocument) => {
    /*
     * No highlight: nothing here is a claim about a value, so the viewer opens the first
     * page plainly. Boxes are what a citation or a table cell brings with it.
     */
    setViewing({
      documentId: document.id,
      filename: document.filename,
      pageIndex: 0,
      boxes: [],
      excerpt: '',
    });
  }, []);

  if (!token) {
    return (
      <Page>
        <AppHeader active="upload" />
        <Main>
          <Note role="alert">
            This workspace needs its access token, and this browser does not have it. Open
            the link you were given in full, including everything after the #.
          </Note>
        </Main>
      </Page>
    );
  }

  return (
    <Page>
      <AppHeader
        active="upload"
        workspace={{
          id: workspaceId,
          label: overview.data?.label ?? 'Untitled workspace',
          documentCount,
        }}
        onAddDocuments={() => addInput.current?.click()}
      />

      <Split>
        <Main>
          <Headline>{sending ? 'Uploading your documents' : 'Your documents'}</Headline>

          {tasks.length > 0 ? (
            <>
              <Carousel>
                <Spiral
                  slides={slides}
                  ariaLabel="The documents being uploaded, turning past one another. Each one is listed with its progress below."
                />
              </Carousel>

              <Summary>
                <SummaryLine>
                  <strong>
                    {arrived} of {tasks.length}
                  </strong>{' '}
                  {tasks.length === 1 ? 'document' : 'documents'} arrived
                  {totalBytes > 0 && (
                    <>
                      {' · '}
                      {formatBytes(sentBytes)} of {formatBytes(totalBytes)}
                    </>
                  )}
                </SummaryLine>
                <TotalBar
                  value={sentBytes}
                  max={Math.max(totalBytes, 1)}
                  aria-label={`Upload progress: ${arrived} of ${tasks.length} documents arrived`}
                />
              </Summary>

              {/*
                `open` rather than `defaultOpen`: a failure that happens while the disclosure
                is shut has to be able to push it open by itself.
              */}
              <Details open={detailsOpen} onToggle={handleToggle}>
                <SummaryToggle data-failed={failed > 0}>
                  <span>
                    {failed > 0
                      ? `${failed === 1 ? 'One file' : `${failed} files`} could not be sent — see every file`
                      : 'See every file'}
                  </span>
                  <span aria-hidden="true">{detailsOpen ? '−' : '+'}</span>
                </SummaryToggle>

                <Panel aria-busy={sending}>
                  {tasks.map((task) => (
                    <UploadRow key={task.key} task={task} />
                  ))}
                </Panel>
              </Details>
            </>
          ) : null}

          {rejected.length > 0 && (
            <div style={{ width: '100%', maxWidth: 880 }}>
              <RejectionNotice rejected={rejected} />
            </div>
          )}

          <Library>
            <LibraryHeading>
              {library.length === 1 ? '1 document' : `${library.length} documents`} in this
              workspace
            </LibraryHeading>
            <DocumentLibrary
              documents={library}
              isPending={overview.isPending}
              onOpen={openDocument}
              onDelete={(document) => removal.mutate(document.id)}
              deletingId={removal.isPending ? (removal.variables ?? null) : null}
            />
            {removal.isError && (
              <Note role="alert">
                That document could not be deleted. It is still here, and nothing was removed
                from the table.
              </Note>
            )}
          </Library>

          <Actions>
            <SecondaryButton type="button" onClick={() => addInput.current?.click()}>
              <Plus size={16} aria-hidden="true" />
              Add more files
            </SecondaryButton>

            <ContinueButton type="button" disabled={sending} onClick={goToChat}>
              Continue
              <ArrowRight size={16} aria-hidden="true" />
            </ContinueButton>
          </Actions>

          {/*
            Said once, here, rather than on every row: "Ready" is about arrival, not about
            being askable. Reading the documents starts now and its progress is on the next
            screen, which is exactly why Continue is worth pressing.
          */}
          {allSettled && (
            <Note role="status">
              {failed > 0
                ? `${failed === 1 ? 'One file' : `${failed} files`} could not be sent. The rest arrived and are being read now — you can follow that on the next screen.`
                : 'All files arrived. Reading them starts now, and you can watch it on the next screen.'}
            </Note>
          )}

          <HiddenInput
            ref={addInput}
            type="file"
            multiple
            accept={ACCEPT_ATTRIBUTE}
            aria-label="Add more documents to this workspace"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              if (files.length > 0) handleAdd(files);
              event.target.value = '';
            }}
          />
        </Main>

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
