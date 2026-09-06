import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Providers } from '../../app/Providers';
import { makeQueryClient } from '../../app/queryClient';
import { useToasts } from '../../ui/toastStore';
import { UploadScreen } from './UploadScreen';
import { usePendingUploads } from './pendingUploads';

/**
 * One screen, two modes (decision D72), so one suite with two halves.
 *
 * **First run** has one job: a person who has never seen this product understands it and
 * can start in one action. The tests hold that job in place — the promise in the headline,
 * both ways in being equally reachable, and a refused file being explained rather than
 * swallowed.
 *
 * **In a workspace** the same page has to be the inventory: what is here, what became of
 * it, and the two things to do next. One test here exists because of a specific failure —
 * the screen once selected from the pending-uploads store with
 * `state.workspaceId === id ? state.files : []`, which allocates a new array on every miss.
 * Zustand compares snapshots by reference, so React re-rendered until it threw "Maximum
 * update depth exceeded" and the page went blank, while the whole suite passed because
 * nothing rendered the component. Rendering it, in both modes, is the assertion that
 * matters.
 *
 * Network is stubbed at `fetch` rather than with MSW: these screens make a handful of calls
 * and the assertions are about what the interface does, not about response shapes.
 */

const WORKSPACE = '33333333-3333-4333-8333-333333333333';

function renderFirstRun() {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<UploadScreen />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  );
}

function renderWorkspace(path = `/w/${WORKSPACE}/upload`) {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/w/:workspaceId/upload" element={<UploadScreen />} />
          {/* A stand-in for the conversation, so "was it taken there" is observable. */}
          <Route path="/w/:workspaceId/chat" element={<p>the conversation</p>} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  );
}

function makeFile(name: string, size = 1024): File {
  const file = new File(['x'], name);
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

/**
 * Drop rather than pick, deliberately.
 *
 * The file input carries an `accept` list, so the native picker — and `userEvent.upload`,
 * which honours it — filters unsupported files out before the application ever sees them.
 * A drag-and-drop does not: the browser hands over whatever was dropped. That is precisely
 * why FR-03 requires the check in application code, so the tests exercise the path where
 * the rule actually has to hold.
 */
function drop(files: File[]) {
  const zone = screen.getByText(/drag files here/i).parentElement!;
  fireEvent.drop(zone, { dataTransfer: { files, types: ['Files'] } });
}

/**
 * A stubbed XMLHttpRequest, in three flavours.
 *
 * `stall` never finishes, which is what most of these tests want: a batch frozen mid-flight
 * is the state the screen exists to render. `succeed` and `fail` complete on the next tick,
 * which is the only way to reach what happens when a batch lands — the toast, and the move
 * to the conversation.
 */
function makeXhr(outcome: 'stall' | 'succeed' | 'fail') {
  return class {
    upload = { addEventListener: () => {} };
    private handlers: Record<string, () => void> = {};
    status = outcome === 'fail' ? 500 : 200;
    response = outcome === 'succeed' ? { accepted: [{ id: 'doc-new' }] } : null;
    responseType = '';

    addEventListener(event: string, handler: () => void) {
      this.handlers[event] = handler;
    }
    open() {}
    setRequestHeader() {}
    send() {
      if (outcome === 'stall') return;
      setTimeout(() => this.handlers.load?.(), 0);
    }
  };
}

const fetchMock = vi.fn();

function requestAt(index: number): Request {
  return fetchMock.mock.calls[index]?.[0] as Request;
}

function respondOnce(body: unknown, status = 200) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

function respondAlways(body: unknown) {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

/**
 * An overview that changes its mind, which is what the screen is built to watch.
 *
 * The first answer has the documents mid-pipeline; every answer after it has them finished.
 * That is the real sequence — the screen refetches when the bytes land and again as
 * documents settle — and it is the only way to reach the behaviour that matters here: the
 * confirmation and the hand-off fire when the documents are READ, not when they arrive
 * (decision D76).
 */
function respondWithPipeline(finalStatus: 'done' | 'failed' = 'done') {
  let call = 0;
  fetchMock.mockImplementation((request: Request) => {
    const url = typeof request === 'string' ? request : request.url;
    if (url.includes('/events')) {
      // No live frames in jsdom; the screen falls back to the overview it is given.
      return Promise.resolve(new Response('', { status: 200 }));
    }
    call += 1;
    const status = call === 1 ? 'extracting' : finalStatus;
    return Promise.resolve(
      new Response(
        JSON.stringify({
          label: 'Q3 Vendor Contracts',
          documents: [
            {
              id: 'doc-1',
              filename: 'invoice_0417.pdf',
              status,
              stage_detail: null,
              failure_reason: status === 'failed' ? 'This PDF is password protected.' : null,
              page_count: 1,
              size_bytes: 1024,
              created_at: '2026-09-06T09:00:00Z',
              source_format: 'pdf',
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
  });
}

const OVERVIEW = {
  label: 'Q3 Vendor Contracts',
  documents: [
    {
      id: 'doc-1',
      filename: 'acme-invoice-2041.pdf',
      status: 'done',
      stage_detail: null,
      failure_reason: null,
      page_count: 2,
      size_bytes: 41000,
      created_at: '2026-09-06T09:00:00Z',
      source_format: 'pdf',
    },
    {
      id: 'doc-2',
      filename: 'scan.png',
      status: 'failed',
      stage_detail: null,
      failure_reason: 'No text could be recognised on this page.',
      page_count: 1,
      size_bytes: 900000,
      created_at: '2026-09-06T09:01:00Z',
      source_format: 'image',
    },
  ],
};

beforeEach(() => {
  usePendingUploads.getState().clear();
  useToasts.getState().clear();
  window.localStorage.setItem(`distill.token.${WORKSPACE}`, 'tok_test');
  fetchMock.mockReset();
  respondAlways(OVERVIEW);
  vi.stubGlobal('fetch', fetchMock);

  // The workspace half sends through XHR; it must not reach a real network either.
  vi.stubGlobal('XMLHttpRequest', makeXhr('stall'));
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('UploadScreen, first run', () => {
  it('names itself and states what it does before anything has been uploaded', () => {
    renderFirstRun();

    // The name is drawn as particles on a canvas, so the accessible name has to come from
    // real text underneath it. Querying by role is what proves the text is actually there.
    expect(screen.getByRole('heading', { name: 'Distill' })).toBeInTheDocument();
    expect(screen.getByText(/pull out what matters/i)).toBeInTheDocument();
  });

  it('offers both ways in, neither buried behind the other', () => {
    renderFirstRun();

    expect(screen.getByRole('button', { name: /choose files/i })).toBeEnabled();
    expect(
      screen.getByRole('button', { name: /try with sample documents/i }),
    ).toBeEnabled();
  });

  it('shows no application chrome, because there is nothing yet to navigate to', () => {
    renderFirstRun();

    // Decision D57: the header is workspace chrome. Before an upload, Chat and Data lead
    // nowhere, so the screen is the product's front door and nothing else.
    expect(screen.queryByRole('banner')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByText('Chat')).not.toBeInTheDocument();
    expect(screen.queryByText('Data')).not.toBeInTheDocument();
  });

  it('shows no document library, because there is no workspace to list', () => {
    renderFirstRun();
    expect(screen.queryByRole('list', { name: /documents in this workspace/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /continue/i })).toBeNull();
  });

  it('gives the file input an accessible name that lists what it accepts', () => {
    renderFirstRun();

    const input = screen.getByLabelText(/choose documents to upload/i);
    expect(input).toHaveAttribute('accept', expect.stringContaining('.pdf'));
    expect(input).toHaveAttribute('multiple');
  });

  it('refuses an unsupported file inline and never contacts the server', async () => {
    renderFirstRun();

    drop([makeFile('slides.key')]);

    const notice = await screen.findByRole('status');
    expect(within(notice).getByText(/slides\.key/)).toBeInTheDocument();
    expect(within(notice).getByText(/cannot read \.key files/i)).toBeInTheDocument();

    // Requirement FR-03: rejected before upload begins, not after a round trip.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('carries a mixed selection onward, refusals included', async () => {
    fetchMock.mockReset();
    respondOnce({
      id: '11111111-1111-4111-8111-111111111111',
      token: 'tok_test',
      created_at: new Date().toISOString(),
    });

    renderFirstRun();

    drop([makeFile('invoice.pdf'), makeFile('slides.key')]);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    // openapi-fetch hands a fully built `Request` to the transport, not (url, init).
    expect(requestAt(0).url).toContain('/api/v1/workspaces');

    // The acceptable file is not uploaded from here: the workspace mode owns the transfer,
    // because only it can report progress per file.
    await waitFor(() => {
      const staged = usePendingUploads.getState();
      expect(staged.files.map((file) => file.name)).toEqual(['invoice.pdf']);
      // And the refusal goes with it, so it is readable on a screen that stays put.
      expect(staged.rejected.map((entry) => entry.file.name)).toEqual(['slides.key']);
    });
  });

  it('creates a workspace and seeds it when asked for the samples', async () => {
    const user = userEvent.setup();
    fetchMock.mockReset();
    respondOnce({
      id: '22222222-2222-4222-8222-222222222222',
      token: 'tok_test',
      created_at: new Date().toISOString(),
    });
    respondOnce({ documents: [] });

    renderFirstRun();
    await user.click(screen.getByRole('button', { name: /try with sample documents/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const seed = requestAt(1);
    expect(seed.url).toContain('/documents/seed');
    expect(seed.method).toBe('POST');
    expect(seed.headers.get('authorization')).toBe('Bearer tok_test');
  });

  it('explains a failure to start instead of leaving the screen inert', async () => {
    const user = userEvent.setup();
    fetchMock.mockReset();
    respondOnce({ detail: 'The database is not reachable.', correlation_id: 'req-42' }, 503);

    renderFirstRun();
    await user.click(screen.getByRole('button', { name: /try with sample documents/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/database is not reachable/i);
    // The correlation id is what turns "it broke" into a traceable bug report.
    expect(alert).toHaveTextContent('req-42');
  });
});

describe('UploadScreen, inside a workspace', () => {
  it('is recognisably the same screen, with the drop zone traded for the two things to do', async () => {
    renderWorkspace();

    // Same page: the name is still the first thing on it.
    expect(await screen.findByRole('heading', { name: 'Distill' })).toBeInTheDocument();

    // Different middle: no drop zone, because the way in from here is the header's control
    // and the button below, and both open the same file picker.
    expect(screen.queryByText(/drag files here/i)).toBeNull();
    expect(screen.getByRole('button', { name: /add more files/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled();
  });

  it('renders without looping when the store holds nothing for this workspace', async () => {
    renderWorkspace();
    expect(await screen.findByRole('heading', { name: 'Distill' })).toBeInTheDocument();
  });

  it('lists what the workspace already holds, with no upload in flight', async () => {
    /*
     * The gap this screen had until decision D71: arriving here with documents indexed
     * said "this browser is not uploading anything right now" and showed nothing at all.
     * A person cannot check what is in a workspace by reading a table built out of it.
     */
    renderWorkspace();

    expect(await screen.findByText('acme-invoice-2041.pdf')).toBeInTheDocument();
    expect(screen.getByText('scan.png')).toBeInTheDocument();
    expect(
      screen.getByText('No text could be recognised on this page.'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('list', { name: /documents in this workspace/i }),
    ).toBeInTheDocument();
  });

  it('lists a row per staged file and holds Continue while they are in flight', async () => {
    usePendingUploads
      .getState()
      .stage(WORKSPACE, [makeFile('invoice_0417.pdf'), makeFile('notes.txt')], []);

    const { container } = renderWorkspace();

    /*
     * Each filename appears more than once: on its row, and on however many cards the
     * spiral needed to close its ring. The row is the one that has to be there, so it is
     * the one asserted — by its progress bar's accessible name, which no card carries.
     */
    await waitFor(() => {
      const rows = container.querySelectorAll('progress[aria-label*="."]');
      const rowLabels = Array.from(rows, (bar) => bar.getAttribute('aria-label') ?? '');
      expect(rowLabels.some((label) => label.startsWith('invoice_0417.pdf: '))).toBe(true);
      expect(rowLabels.some((label) => label.startsWith('notes.txt: '))).toBe(true);
    });

    expect(screen.getAllByText('invoice_0417.pdf').length).toBeGreaterThan(0);

    // The point of holding here: nothing in this workspace can be asked about yet, so the
    // way forward stays shut until the first document has been read.
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled();
  });

  it('answers "how much longer" once, above the per-file detail', async () => {
    usePendingUploads
      .getState()
      .stage(WORKSPACE, [makeFile('invoice_0417.pdf'), makeFile('notes.txt')], []);

    renderWorkspace();

    // The aggregate is what a person waiting actually wants; the rows are the audit trail.
    expect(await screen.findByText(/0 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/documents arrived/)).toBeInTheDocument();
    expect(screen.getByText(/see every file/i)).toBeInTheDocument();
  });

  it('keeps the spiral out of the accessibility tree, since the rows say the same thing', async () => {
    usePendingUploads.getState().stage(WORKSPACE, [makeFile('invoice_0417.pdf')], []);

    const { container } = renderWorkspace();
    await waitFor(() =>
      expect(screen.getAllByText('invoice_0417.pdf').length).toBeGreaterThan(1),
    );

    // Decorative: a screen reader that walked ten repeated cards would learn nothing the
    // list below does not already say, at ten times the length.
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('takes the staged files so a remount does not upload them twice', async () => {
    usePendingUploads.getState().stage(WORKSPACE, [makeFile('invoice_0417.pdf')], []);

    renderWorkspace();

    await waitFor(() => expect(usePendingUploads.getState().files).toHaveLength(0));
  });

it('turns the spiral for documents being read, with nothing being uploaded', async () => {
    /*
     * The sample-documents path. Nothing leaves this browser — the server already has the
     * files — and cutting the animation there left the one route a reviewer is most likely
     * to take with a list and a progress bar. Decision D79.
     */
    respondWithPipeline('done');
    renderWorkspace();

    await waitFor(() =>
      // One row, plus however many cards the ring needed to close itself.
      expect(screen.getAllByText('invoice_0417.pdf').length).toBeGreaterThan(1),
    );
    expect(usePendingUploads.getState().files).toHaveLength(0);
  });

  it('names the workspace in the header once the overview arrives', async () => {
    renderWorkspace();

    expect(await screen.findByText('Q3 Vendor Contracts')).toBeInTheDocument();
  });

  it('says plainly when the token is missing rather than showing an empty workspace', async () => {
    window.localStorage.clear();
    renderWorkspace();

    expect(await screen.findByRole('alert')).toHaveTextContent(/access token/i);
  });
});

describe('UploadScreen, when a batch lands', () => {
  it('waits for the documents to be READ, then confirms and opens the way forward', async () => {
    /*
     * Decisions D76 and D80. "Arrived" is the wrong moment to celebrate: bytes on a disk
     * cannot be asked about, so the screen waits for the pipeline. What it does NOT do any
     * more is walk the person to the conversation itself — it says the documents are ready
     * and lets go of Continue, which leaves the choice where it belongs.
     */
    vi.stubGlobal('XMLHttpRequest', makeXhr('succeed'));
    respondWithPipeline('done');
    usePendingUploads.getState().stage(WORKSPACE, [makeFile('invoice_0417.pdf')], []);

    renderWorkspace();

    await waitFor(() =>
      expect(useToasts.getState().toasts.map((toast) => toast.message)).toEqual([
        '1 document ready. You can ask about it now.',
      ]),
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled(),
    );

    // Given time to have moved on its own, and still here.
    await new Promise((resolve) => setTimeout(resolve, 1400));
    expect(screen.queryByText('the conversation')).not.toBeInTheDocument();
  });

  it('holds Continue while the documents this visit started are still being read', async () => {
    /*
     * The sample-documents path: no bytes leave this browser, so there is nothing for an
     * upload bar to wait on — only the reading, which is the thing that decides whether the
     * next screen has anything to answer with.
     */
    usePendingUploads.getState().stage(WORKSPACE, [], []);
    respondAlways({
      label: 'Q3 Vendor Contracts',
      documents: [
        {
          id: 'doc-1',
          filename: 'invoice_0417.pdf',
          status: 'extracting',
          stage_detail: null,
          failure_reason: null,
          page_count: 1,
          size_bytes: 1024,
          created_at: '2026-09-06T09:00:00Z',
          source_format: 'pdf',
        },
      ],
    });

    renderWorkspace();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled(),
    );
    expect(useToasts.getState().toasts).toHaveLength(0);
  });

  it('opens Continue as soon as the FIRST document is ready, not the last', async () => {
    /*
     * Decision D82. The next screen is a conversation over whatever has been indexed, so
     * one read document is enough to hold one. Waiting for the last file of a batch let the
     * slowest document decide when anybody could start.
     */
    usePendingUploads.getState().stage(WORKSPACE, [], []);
    respondAlways({
      label: 'Q3 Vendor Contracts',
      documents: [
        {
          id: 'doc-1',
          filename: 'invoice_0417.pdf',
          status: 'done',
          stage_detail: null,
          failure_reason: null,
          page_count: 1,
          size_bytes: 1024,
          created_at: '2026-09-06T09:00:00Z',
          source_format: 'pdf',
        },
        {
          id: 'doc-2',
          filename: 'contract-later.pdf',
          status: 'extracting',
          stage_detail: null,
          failure_reason: null,
          page_count: 9,
          size_bytes: 90000,
          created_at: '2026-09-06T09:01:00Z',
          source_format: 'pdf',
        },
      ],
    });

    renderWorkspace();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled(),
    );

    // Still reading the second one, and saying so — the button opening is not a claim that
    // the workspace is finished.
    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
  });

  it('says nothing and holds nothing when the Upload tab is simply reopened', async () => {
    /*
     * The bug this exists to keep out (decision D80). The event stream is resumable from a
     * persisted log, so reopening the Upload tab on a finished workspace can replay a
     * document moving through the pipeline. That once read as a fresh batch landing: the
     * confirmation fired again and the screen walked the person to the conversation they
     * had just navigated away from. Nothing was staged for this visit, so nothing is
     * announced and Continue never shuts.
     */
    respondWithPipeline('done');

    renderWorkspace();

    await screen.findAllByText('invoice_0417.pdf');
    await new Promise((resolve) => setTimeout(resolve, 1400));

    expect(useToasts.getState().toasts).toHaveLength(0);
    expect(screen.queryByText('the conversation')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled();
  });

  it('stays put when something could not be used, because that is the part worth reading', async () => {
    vi.stubGlobal('XMLHttpRequest', makeXhr('succeed'));
    respondWithPipeline('failed');
    usePendingUploads.getState().stage(WORKSPACE, [makeFile('invoice_0417.pdf')], []);

    renderWorkspace();

    await waitFor(() => {
      const [toast] = useToasts.getState().toasts;
      expect(toast?.tone).toBe('warning');
      expect(toast?.message).toMatch(/could not be used/i);
    });

    // Given time to have navigated, and still here.
    await new Promise((resolve) => setTimeout(resolve, 1200));
    expect(screen.queryByText('the conversation')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled();
  });

  it('does not move someone who added files from inside their own library', async () => {
    /*
     * The same event, a different intent. Someone standing in their library who adds a file
     * is looking at the library; taking the screen away would be answering a question they
     * did not ask.
     */
    const user = userEvent.setup();
    vi.stubGlobal('XMLHttpRequest', makeXhr('succeed'));
    respondWithPipeline('done');

    renderWorkspace();
    // On a card in the spiral as well as in the library row, so more than one match.
    await screen.findAllByText('invoice_0417.pdf');

    const input = screen.getByLabelText(/add more documents/i);
    await user.upload(input, makeFile('added-later.pdf'));

    await waitFor(() => expect(useToasts.getState().toasts).toHaveLength(1));

    await new Promise((resolve) => setTimeout(resolve, 1400));
    expect(screen.queryByText('the conversation')).not.toBeInTheDocument();
  });
});
