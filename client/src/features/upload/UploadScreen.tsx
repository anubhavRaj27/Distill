import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import styled from 'styled-components';

import { api, authHeader, toFailure } from '../../api/client';
import { AppHeader } from '../../app/AppHeader';
import { useRenameWorkspace } from '../../app/useRenameWorkspace';
import {
  ACCEPT_ATTRIBUTE,
  formatBytes,
  sortIntake,
  type RejectedFile,
} from '../../lib/files';
import { logger } from '../../lib/logger';
import { makeTasks, runBatch, type UploadTask } from '../../lib/upload';
import { consumeTokenFromFragment, recallToken } from '../../lib/workspace-token';
import { ParticleText } from '../../ui/ParticleText';
import { Spiral } from '../../ui/Spiral';
import { theme } from '../../ui/theme';
import { useToasts } from '../../ui/toastStore';
import { isSettled } from '../processing/stageWords';
import { useDocumentProgress } from '../processing/useDocumentProgress';
import { SourceViewer, type SourceTarget } from '../viewer/SourceViewer';
import { DocumentCard } from './components/DocumentCard';
import { DropZone } from './components/DropZone';
import { RejectionNotice } from './components/RejectionNotice';
import { UploadRow } from './components/UploadRow';
import { DocumentLibrary, type LibraryDocument } from './DocumentLibrary';
import { usePendingUploads } from './pendingUploads';
import { useDeleteDocument } from './useDeleteDocument';
import { useStartWorkspace } from './useStartWorkspace';

/**
 * Screen 1 of three: Upload. Routes `/` and `/w/{id}/upload`. Requirements section 3.1.
 *
 * ONE SCREEN, TWO MODES (decision D72)
 * ------------------------------------
 * These were two files that rendered two different products. The first-run screen is the
 * name, a sentence, a drop zone; the workspace screen was a headline, a wide band of
 * nothing, and a list. Arriving at the second from the header's Upload tab did not read as
 * the same place at all, and the emptiness was the tell: the layout had been built around a
 * drop zone that is not there once a workspace exists.
 *
 * So the page is one shape in both modes — the name, then the way to put documents in, then
 * whatever there is to say about the documents already in — and what changes is the middle:
 *
 * - **First run** (`/`, no workspace): the drop zone and "Try with sample documents", with
 *   nothing below because there is nothing yet. No application header: Chat and Data lead
 *   nowhere before a workspace exists (decision D57).
 * - **In a workspace** (`/w/{id}/upload`): "Add more files" and "Continue" where the drop
 *   zone was, and under them the library — every document, what became of it, and a way to
 *   open or delete it (decision D71). Bytes still in flight draw the spiral above the
 *   actions while they last.
 *
 * The hero is deliberately smaller in the second mode. It is the same page and should look
 * it, but a 210px canvas above a list of ten files is the empty space this merge was meant
 * to remove.
 *
 * WHY EVERY HOOK RUNS IN BOTH MODES
 * ---------------------------------
 * Hooks cannot be conditional, so the workspace hooks run on `/` too. They are inert there
 * rather than wasteful: there is no token, so the query is disabled, the event stream is
 * never opened, and the mutations are never fired. The alternative — two components sharing
 * a layout by props — was what this replaced.
 *
 * Processing (parse, extract, index) deliberately does **not** hold anyone here. It runs on
 * the server and streams `document.status` events, which the processing strip renders on
 * Chat and Data (requirement FR-04) and which this screen lays over each library row.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

/**
 * The viewer is a panel beside the content, not below it, so this screen splits
 * horizontally under the header exactly as Chat does. Without it the `aside` becomes the
 * next row of a column layout and opens somewhere off the bottom of the page.
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
  padding: ${({ theme }) => theme.space.page} ${({ theme }) => theme.space.xl};

  /* First run has nothing below the fold, so it sits in the middle of the screen. */
  &[data-mode='first-run'] {
    justify-content: center;
  }

  /*
   * The workspace state arrives rather than appearing. Dropping files navigates, which
   * remounts this screen (decision D72), and without an entrance the front door is
   * replaced by a different page between two frames — the drop zone gone, the header
   * suddenly there, the hero a different size. A fade with a small rise over half a second
   * makes it read as the same page changing its mind.
   *
   * GlobalStyle zeroes animation durations under a reduced-motion preference, so this
   * needs no guard of its own.
   */
  &[data-mode='workspace'] {
    animation: screen-in ${({ theme }) => theme.motion.settle} both;
  }

  @keyframes screen-in {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
`;

const Title = styled.h1`
  width: 100%;
  max-width: ${({ theme }) => theme.measure.prose};
  margin: 0;

  /*
   * Scaled down into place. The name is 176px on the front door and 104px here, and a
   * canvas cannot tween between two rasterisations across a remount, so the smaller one
   * starts slightly large and settles. It covers the size change with the motion the eye
   * expects from something arriving.
   */
  &[data-mode='workspace'] {
    animation: hero-settle ${({ theme }) => theme.motion.settle} both;
    transform-origin: center top;
  }

  @keyframes hero-settle {
    from {
      opacity: 0;
      transform: scale(1.12);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
`;

const Standfirst = styled.p`
  margin-top: ${({ theme }) => theme.space.xs};
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 15px;
  line-height: 1.7;
  text-align: center;
  text-wrap: pretty;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Intake = styled.div`
  margin-top: ${({ theme }) => theme.space.xxl};
  width: 640px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;

  /*
   * Creating a workspace takes a round trip, and until it returns nothing on this screen
   * moved: the files were dropped, the drop zone went quietly disabled, and the page sat
   * there looking ignored. Receding slightly is the acknowledgement, and it is also the
   * first half of the transition the workspace state finishes.
   */
  transition:
    opacity ${({ theme }) => theme.motion.settle},
    transform ${({ theme }) => theme.motion.settle};

  &[data-starting='true'] {
    opacity: 0.35;
    transform: scale(0.985);
  }
`;

/**
 * The sample path, requirement FR-05.
 *
 * Quieter than "Choose files" but immediately below it, because for a first-time visitor
 * with nothing to hand it is the more useful of the two. It is a real button, not a link:
 * it performs an action rather than navigating.
 */
const SampleAction = styled.button`
  appearance: none;
  margin-top: ${({ theme }) => theme.space.lg};
  padding: 4px 8px;

  font-family: inherit;
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: none;
  border: 0;
  cursor: pointer;
  transition: color ${({ theme }) => theme.motion.quick};

  span {
    color: ${({ theme }) => theme.color.ink};
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  &:hover:not(:disabled) {
    color: ${({ theme }) => theme.color.ink};
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
`;

const StartError = styled.p`
  margin-top: ${({ theme }) => theme.space.lg};
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 13px;
  text-align: center;
  color: ${({ theme }) => theme.tier.conflict.color};

  code {
    font-family: ${({ theme }) => theme.font.mono};
    font-size: 12px;
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

/** What will and will not be taken, stated before anyone tries. Requirement FR-03. */
const Formats = styled.p`
  margin-top: ${({ theme }) => theme.space.xxl};
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: ${({ theme }) => theme.color.inkMuted};
  opacity: 0.75;
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
  margin-top: ${({ theme }) => theme.space.xl};
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

/** Where the drop zone is on the first run: the two things to do from here instead. */
const Actions = styled.div`
  width: 100%;
  max-width: 880px;
  margin-top: ${({ theme }) => theme.space.xl};
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

/**
 * The route adapter, and the reason it exists.
 *
 * `/` and `/w/{id}/upload` are one component (decision D72), so React keeps the same
 * instance mounted across the navigation between them. Nearly everything below is read
 * ONCE, on mount: the workspace token, the files staged for this workspace, whether the
 * batch has been started. Sharing an instance quietly broke all of it — dropping files on
 * the first run created the workspace, navigated, and then told the person their token was
 * missing, because the token had been read on a screen that had no workspace yet.
 *
 * Keying by workspace restores mount-per-workspace, which is what the two separate screens
 * had by construction. It is three lines here instead of a defensive rewrite of every piece
 * of state below, and it says the real rule out loud: this screen is mounted FOR a
 * workspace.
 */
export function UploadScreen() {
  const { workspaceId } = useParams();
  return <UploadScreenFor key={workspaceId ?? 'first-run'} />;
}

function UploadScreenFor() {
  const { workspaceId = '' } = useParams();
  const inWorkspace = workspaceId !== '';
  const navigate = useNavigate();
  const addInput = useRef<HTMLInputElement>(null);

  const [token] = useState(
    () => consumeTokenFromFragment(workspaceId) ?? recallToken(workspaceId),
  );

  // -- First run -----------------------------------------------------------

  const start = useStartWorkspace();
  const starting = start.isPending;

  // -- The batch this browser is sending ------------------------------------

  /*
   * Taken once, on mount. The store exists only to survive the navigation from the first
   * run into the workspace.
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
  const mine = inWorkspace && pendingWorkspaceId === workspaceId;
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

  /**
   * Whether THIS visit set work going, rather than merely opening the tab.
   *
   * True at mount when the pending store holds an entry for this workspace — the samples
   * path stages an empty selection precisely so this still reads true — and set again when
   * files are added from inside the workspace. The confirmation and the Continue button
   * both key off it, so opening the Upload tab on a workspace that finished long ago
   * announces nothing and holds nothing (decision D80).
   */
  const [workStartedHere, setWorkStartedHere] = useState(mine);
  const showToast = useToasts((state) => state.show);

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    /*
     * Cleared for every arrival from the first run, not only for one carrying files. The
     * samples path stages an empty selection, so clearing this inside the "there are tasks"
     * branch left the entry in the store for the life of the tab — and every later visit to
     * the Upload tab then read as a fresh arrival and replayed the whole handoff.
     */
    if (mine) clearPending();
    if (tasks.length === 0) return;
    logger.event('upload.start', { files: tasks.length });
    void send(tasks);
    // `tasks` is the initial batch; later additions are sent by their own handler.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -- What the server holds -------------------------------------------------

  const overview = useQuery({
    queryKey: ['workspace', workspaceId],
    enabled: Boolean(token) && inWorkspace,
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/workspaces/{workspace_id}', {
        params: { path: { workspace_id: workspaceId }, header: authHeader(token!) },
      });
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },
  });

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
    /*
     * Driven by `progress`, which already merges the overview's documents with everything
     * the event stream has said. Driving it from the overview instead meant a document was
     * invisible until the next refetch — so an upload, or a click on "Try with sample
     * documents", showed an empty library for the entire time the reading was happening,
     * which is the only time anyone is watching. Decision D76.
     */
    const described = new Map(stored.map((document) => [document.id, document]));
    return progress.map((entry) => {
      const document = described.get(entry.documentId);
      return {
        id: entry.documentId,
        filename: entry.filename || document?.filename || 'Document',
        status: document?.status ?? entry.status,
        stage_detail: document?.stage_detail ?? null,
        failure_reason: document?.failure_reason ?? null,
        page_count: document?.page_count ?? null,
        size_bytes: document?.size_bytes,
        source_format: document?.source_format,
        created_at: document?.created_at,
        liveStatus: entry.status,
        liveStageDetail: entry.stageDetail,
        liveFailureReason: entry.failureReason,
      };
    });
  }, [progress, stored]);

  /*
   * A document reaching a terminal stage changes what the overview says about it — the page
   * count, the failure reason — and the overview is a snapshot taken before any of that
   * happened. Refetching when the number of settled documents grows keeps the rows honest
   * without polling: the stream says when there is something new to ask for.
   */
  /*
   * Where the whole workspace is, not where the transfer is. "Ready" means read, extracted
   * and indexed — the point at which a document can actually be asked about — which is what
   * this screen now waits for and reports (decision D76).
   */
  const readCount = library.filter(
    (document) => (document.liveStatus ?? document.status) === 'done',
  ).length;
  const unreadableCount = library.filter(
    (document) => (document.liveStatus ?? document.status) === 'failed',
  ).length;
  const settledCount = readCount + unreadableCount;
  const everythingRead = library.length > 0 && settledCount === library.length;
  const refetchedAt = useRef(0);
  const refetchOverview = overview.refetch;
  useEffect(() => {
    /*
     * Counted from the LIVE stream rather than from the cached list, and refetched rather
     * than invalidated. Both were wrong the other way round, and each failure was silent:
     *
     * - Counting the cache cannot see a first upload at all. The overview was fetched when
     *   the workspace was empty, so there is nothing in it to reach a terminal state, and
     *   the list stayed empty while the document sat there indexed.
     * - `invalidateQueries` did not put new data on this screen. A remount showed the
     *   document immediately, so the data was there to be had; asking this query for it
     *   directly is what actually updates the screen.
     *
     * The ref is the loop guard: the refetch is what changes what this effect reads.
     */
    if (settledCount <= refetchedAt.current) return;
    refetchedAt.current = settledCount;
    void refetchOverview();
  }, [settledCount, refetchOverview]);

  const removal = useDeleteDocument(workspaceId, token);
  const rename = useRenameWorkspace(workspaceId, token);
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

  // -- Taking files, in either mode -----------------------------------------

  const handleFiles = useCallback(
    (files: File[]) => {
      const { accepted, rejected: refused } = sortIntake(files);

      // Requirement FR-03: refusals are shown inline and immediately, before any bytes
      // leave the browser. A mixed selection still uploads what it can — refusing a whole
      // batch over one bad file would be the wrong trade for someone dropping a folder.
      if (refused.length > 0) {
        logger.event('files.rejected', {
          count: refused.length,
          reasons: refused.map((entry) => entry.reason),
        });
      }

      if (!inWorkspace) {
        if (accepted.length > 0) {
          // The refusals travel with the batch: this screen is about to be replaced, and a
          // notice rendered here would vanish in the same tick it appeared.
          start.mutate({ kind: 'files', files: accepted, rejected: refused });
          return;
        }
        // Nothing acceptable, so nobody is going anywhere. Report it right here.
        setRejected(refused);
        return;
      }

      setRejected(refused);
      if (accepted.length === 0) return;
      const added = makeTasks(accepted).map((task) => ({
        ...task,
        key: `${task.key}-${Date.now()}`,
      }));
      setTasks((current) => [...current, ...added]);
      setWorkStartedHere(true);
      void send(added);
    },
    [inWorkspace, send, start],
  );

  const handleSamples = useCallback(() => {
    setRejected([]);
    start.mutate({ kind: 'samples' });
  }, [start]);

  // -- Derived state for the batch ------------------------------------------

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
   * What Continue waits for: the FIRST document this visit set going becoming askable.
   *
   * Not all of them. The next screen is a conversation over whatever has been indexed, and
   * one read document is enough to hold one — the rest arrive underneath it while the
   * person is typing, which is exactly what the processing strip over there is for. Holding
   * the button until the last file of a ten-file batch finished was making the slowest
   * document in the pile decide when anyone could start.
   *
   * Only this visit's work, and released the moment there is nothing left to wait for:
   * `everythingRead` covers a batch that arrived and could not be read, `nothingArrived` a
   * batch where no file made it off this machine. Holding the button in either case would
   * strand the person on this screen with no way forward and nothing coming.
   */
  const nothingArrived = allSettled && arrived === 0;
  const stillWorking =
    workStartedHere && readCount === 0 && !everythingRead && !nothingArrived;

  /**
   * A task's document, once the server has accepted it, so the row can carry on past
   * "Sent" into what is being done with the file. Keyed by the id the upload returned.
   */
  const stageFor = useCallback(
    (task: UploadTask) => {
      if (!task.documentId) return undefined;
      const entry = progress.find((item) => item.documentId === task.documentId);
      if (!entry) return undefined;
      return {
        status: entry.status,
        detail: entry.stageDetail,
        failureReason: entry.failureReason,
      };
    },
    [progress],
  );

  /*
   * One card per document, in order. `Spiral` repeats them itself when there are too few to
   * close the ring, so a single document still turns rather than hanging there.
   *
   * Two sources, one ring (decision D79). When this browser is sending files, the cards are
   * those files — real thumbnails for images, because the bytes are here. When it is not,
   * which is the whole of the sample-documents path, the cards are the documents the server
   * is reading. Cutting the second case is what took the animation off the samples path
   * entirely, leaving the demo route with a list and a progress bar where the product's one
   * piece of theatre should be.
   */
  const slides = useMemo(() => {
    if (tasks.length > 0) {
      return tasks.map((task) => ({
        key: task.key,
        node: (
          <DocumentCard
            document={{ filename: task.file.name, file: task.file, phase: task.phase }}
          />
        ),
      }));
    }
    return library.map((document) => {
      const status = document.liveStatus ?? document.status;
      const phase =
        status === 'done'
          ? 'ready'
          : status === 'failed'
            ? 'failed'
            : status === 'uploaded'
              ? 'waiting'
              : 'sending';
      return {
        key: document.id,
        node: <DocumentCard document={{ filename: document.filename, phase }} />,
      };
    });
  }, [library, tasks]);

  const documentCount =
    tasks.length > 0 && !overview.data
      ? tasks.filter((task) => task.phase === 'ready').length
      : library.length;

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
   */
  /*
   * The batch has landed, and this screen says so rather than acting on it.
   *
   * It used to hand the person to the conversation on its own. That was right exactly once
   * — the first arrival, when the conversation is where they were heading anyway — and
   * wrong every time afterwards, because the same signal fired again on every later visit
   * to the Upload tab and took the tab away from someone who had deliberately opened it.
   * The move is now the Continue button, held shut while this visit's work is in flight,
   * which says the same thing without steering (decision D80).
   *
   * The confirmation stays: it is the moment worth marking, and it is raised through the
   * store rather than rendered here so it survives whatever the person does next
   * (decision D73).
   *
   * Nothing is announced until work has actually been watched, and only work THIS visit
   * set going. Without the first, an empty list is trivially all-settled and the screen
   * congratulates itself before the server has said anything; without the second, the
   * event stream replaying a finished workspace's history re-announces documents that were
   * read minutes ago.
   */
  const sawWorkInProgress = useRef(false);
  if (
    workStartedHere &&
    library.some((document) => !isSettled(document.liveStatus ?? document.status))
  ) {
    sawWorkInProgress.current = true;
  }

  const announced = useRef(false);
  useEffect(() => {
    if (!workStartedHere || !everythingRead || !sawWorkInProgress.current) return;
    if (announced.current) return;
    announced.current = true;

    /*
     * The documents are read, not merely received. This is the moment worth confirming and
     * the moment worth moving on from — the whole reason this screen now waits for the
     * pipeline rather than for the last byte (decision D76).
     */
    const readWord = readCount === 1 ? '1 document' : `${readCount} documents`;
    if (unreadableCount > 0 || failed > 0) {
      const badCount = unreadableCount + failed;
      showToast(
        `${readWord} ready. ${badCount === 1 ? 'One file' : `${badCount} files`} could not ` +
          `be used, and ${badCount === 1 ? 'it is' : 'they are'} listed below.`,
        { tone: 'warning' },
      );
      return;
    }

    showToast(`${readWord} ready. You can ask about ${readCount === 1 ? 'it' : 'them'} now.`);
  }, [everythingRead, failed, readCount, showToast, unreadableCount, workStartedHere]);

  /* The bytes landing is its own, quieter moment: it is when the overview is worth asking
   * again, because the documents that just arrived are not in the copy this screen has. */
  useEffect(() => {
    if (!allSettled) return;
    void refetchOverview();
  }, [allSettled, refetchOverview]);

  const goToChat = useCallback(() => {
    void navigate(`/w/${workspaceId}/chat`);
  }, [navigate, workspaceId]);

  if (inWorkspace && !token) {
    return (
      <Page>
        <AppHeader active="upload" />
        <Main data-mode="workspace">
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
      {inWorkspace && (
        <AppHeader
          active="upload"
          workspace={{
            id: workspaceId,
            label: overview.data?.label ?? 'Untitled workspace',
            documentCount,
          }}
          onAddDocuments={() => addInput.current?.click()}
          onRename={(label) => rename.mutate(label)}
        />
      )}

      <Split>
        <Main data-mode={inWorkspace ? 'workspace' : 'first-run'}>
          <Title data-mode={inWorkspace ? 'workspace' : 'first-run'}>
            <ParticleText
              text="Distill"
              fontFamily={theme.font.display}
              /*
               * Smaller inside a workspace. The same argument does not need making twice at
               * full volume, and the space belongs to the documents once there are some.
               *
               * Denser sampling with it: the step through the rasterised word is in pixels,
               * so the same density at half the size puts half as many particles across a
               * stroke and the letterforms go ragged.
               */
              fontSize={inWorkspace ? 104 : 176}
              height={inWorkspace ? 124 : 210}
              particleDensity={inWorkspace ? 2 : 3}
              particleSize={inWorkspace ? 1.2 : 1.5}
            />
          </Title>

          {!inWorkspace && (
            <Standfirst>
              Drop in a pile of documents. We read them and pull out what matters, into one
              table you can search, question, and trace back to the page it came from.
            </Standfirst>
          )}

          {inWorkspace ? (
            <>
              {(tasks.length > 0 || (slides.length > 0 && !everythingRead)) && (
                <>
                  <Carousel>
                    <Spiral
                      slides={slides}
                      ariaLabel="The documents being uploaded, turning past one another. Each one is listed with its progress below."
                    />
                  </Carousel>


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
                        <UploadRow key={task.key} task={task} stage={stageFor(task)} />
                      ))}
                    </Panel>
                  </Details>
                </>
              )}

              {(tasks.length > 0 || (library.length > 0 && !everythingRead)) && (
                    <Summary>
                      {sending ? (
                        <>
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
                        </>
                      ) : (
                        /*
                         * The bytes are in and the interesting part has started. The bar
                         * switches to the pipeline: what has been read, out of what there is.
                         */
                        <>
                          <SummaryLine>
                            <strong>
                              {readCount} of {library.length}
                            </strong>{' '}
                            {library.length === 1 ? 'document' : 'documents'} ready
                            {unreadableCount > 0 && (
                              <>
                                {' · '}
                                {unreadableCount} could not be read
                              </>
                            )}
                          </SummaryLine>
                          <TotalBar
                            value={settledCount}
                            max={Math.max(library.length, 1)}
                            aria-label={`Reading progress: ${readCount} of ${library.length} documents ready`}
                          />
                        </>
                      )}
                    </Summary>
              )}

              {rejected.length > 0 && (
                <div style={{ width: '100%', maxWidth: 880 }}>
                  <RejectionNotice rejected={rejected} />
                </div>
              )}

              <Actions>
                <SecondaryButton type="button" onClick={() => addInput.current?.click()}>
                  <Plus size={16} aria-hidden="true" />
                  Add more files
                </SecondaryButton>

                <ContinueButton type="button" disabled={stillWorking} onClick={goToChat}>
                  Continue
                  <ArrowRight size={16} aria-hidden="true" />
                </ContinueButton>
              </Actions>

              {/*
                Said once, here, rather than on every row: "Ready" is about arrival, not
                about being askable. The reading happens on this screen now, and Continue
                waits for the first document to finish it — the summary above is what the
                button is waiting on.
              */}
              {allSettled && (
                <Note role="status">
                  {failed > 0
                    ? `${failed === 1 ? 'One file' : `${failed} files`} could not be sent. The rest arrived and are being read now; they will fill in above as they finish.`
                    : 'All files arrived. Reading them starts now; they will fill in above as they finish. Continue opens as soon as the first one is ready.'}
                </Note>
              )}

              <Library>
                <LibraryHeading>
                  {library.length === 1 ? '1 document' : `${library.length} documents`} in
                  this workspace
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
                    That document could not be deleted. It is still here, and nothing was
                    removed from the table.
                  </Note>
                )}
              </Library>
            </>
          ) : (
            <>
              <Intake aria-busy={starting} data-starting={starting}>
                <DropZone onFiles={handleFiles} disabled={starting} />

                {rejected.length > 0 && <RejectionNotice rejected={rejected} />}

                {start.isError ? (
                  <StartError role="alert">
                    {start.error.message}
                    {start.error.correlationId && (
                      <>
                        {' '}
                        <code>{start.error.correlationId}</code>
                      </>
                    )}
                  </StartError>
                ) : (
                  <SampleAction type="button" disabled={starting} onClick={handleSamples}>
                    {starting && start.variables?.kind === 'samples' ? (
                      'Loading sample documents…'
                    ) : (
                      <>
                        No documents to hand? <span>Try with sample documents</span>
                      </>
                    )}
                  </SampleAction>
                )}
              </Intake>

              <Formats>PDF · DOCX · XLSX · CSV · Images · Text</Formats>
            </>
          )}

          <HiddenInput
            ref={addInput}
            type="file"
            multiple
            accept={ACCEPT_ATTRIBUTE}
            aria-label="Add more documents to this workspace"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              if (files.length > 0) handleFiles(files);
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
