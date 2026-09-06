import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Providers } from '../../app/Providers';
import { makeQueryClient } from '../../app/queryClient';
import { ChatScreen } from './ChatScreen';

/**
 * The screen, driven by a real Server-Sent Events body.
 *
 * The stream is stubbed at `fetch` with an actual `ReadableStream` rather than by mocking
 * the parser, because the things that break here are transport things — a frame arriving
 * in two pieces, an event applied out of order — and a mocked parser cannot see any of
 * them. What is asserted is the contract in requirements section 3.2: the sources appear
 * before the prose, the visual's figures come from the server's data model, and a citation
 * opens the source it names.
 */

const WORKSPACE = '55555555-5555-4555-8555-555555555555';
const MESSAGE = '66666666-6666-4666-8666-666666666666';

function renderScreen() {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <MemoryRouter initialEntries={[`/w/${WORKSPACE}/chat`]}>
        <Routes>
          <Route path="/w/:workspaceId/chat" element={<ChatScreen />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  );
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

/** An SSE body delivering `frames` in order, as separate chunks. */
function sse(frames: { event: string; data: unknown; id?: number }[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        frames.forEach((frame, index) => {
          controller.enqueue(
            encoder.encode(
              `id: ${frame.id ?? index + 1}\n` +
                `event: ${frame.event}\n` +
                `data: ${JSON.stringify(frame.data)}\n\n`,
            ),
          );
        });
        controller.close();
      },
    }),
    { status: 200, headers: { 'content-type': 'text/event-stream' } },
  );
}

const SOURCES = [
  {
    chunk_id: 'chunk-1',
    document_id: 'doc-1',
    filename: 'contract_v2.pdf',
    page_index: 3,
    is_digest: false,
  },
  {
    chunk_id: 'chunk-2',
    document_id: 'doc-2',
    filename: 'vendor_terms.docx',
    page_index: 1,
    is_digest: false,
  },
];

/** A surface exactly as `server/app/a2ui/build.py` emits one. */
const SURFACE = [
  { version: 'v0.9', createSurface: { surfaceId: 's1', catalogId: 'distill.app:v2' } },
  {
    version: 'v0.9',
    updateDataModel: {
      surfaceId: 's1',
      path: '/result',
      value: {
        title: 'Spend by vendor (Q3)',
        unit: 'USD',
        rows: [
          { label: 'Argosy Logistics', value: 184200 },
          { label: 'Northfield Supply', value: 142900 },
        ],
      },
    },
  },
  {
    version: 'v0.9',
    updateComponents: {
      surfaceId: 's1',
      components: [
        { id: 'root', component: 'Column', children: ['title', 'visual'] },
        { id: 'title', component: 'Text', text: { path: '/result/title' }, variant: 'h3' },
        {
          id: 'visual',
          component: 'BarChart',
          rows: { path: '/result/rows' },
          xKey: 'label',
          yKey: 'value',
          unit: 'USD',
        },
      ],
    },
  },
];

const CITATION = {
  type: 'citation',
  n: 1,
  chunk_id: 'chunk-1',
  document_id: 'doc-1',
  filename: 'contract_v2.pdf',
  page_index: 3,
  boxes: [{ x0: 72, top: 120, x1: 400, bottom: 134 }],
  excerpt: 'September surcharge added $31,400 to the freight total',
};

const ANSWER_FRAMES = [
  { event: 'status', data: { type: 'status', stage: 'retrieving' } },
  { event: 'sources', data: { type: 'sources', sources: SOURCES } },
  { event: 'status', data: { type: 'status', stage: 'reading' } },
  {
    event: 'visual',
    data: {
      type: 'visual',
      kind: 'bar',
      title: 'Spend by vendor (Q3)',
      surface: SURFACE,
    },
  },
  { event: 'status', data: { type: 'status', stage: 'answering' } },
  { event: 'token', data: { type: 'token', text: 'Total spend is $501,650. ' } },
  { event: 'citation', data: CITATION },
  { event: 'token', data: { type: 'token', text: 'Argosy is largest[^1].' } },
  {
    event: 'done',
    data: {
      type: 'done',
      message: {
        id: MESSAGE,
        role: 'assistant',
        status: 'done',
        content: 'Total spend is $501,650. Argosy is largest[^1].',
        sources: SOURCES,
        citations: [{ ...CITATION, type: undefined }],
        visual: { kind: 'bar', title: 'Spend by vendor (Q3)' },
        surface: SURFACE,
      },
    },
  },
];

const fetchMock = vi.fn();

/**
 * Route a request by URL.
 *
 * The screen opens two streams on mount — the workspace event stream and, once asked, the
 * answer stream — plus three JSON calls. Dispatching on the URL keeps the test readable
 * where an ordered queue of `mockResolvedValueOnce` would break on any reordering.
 */
function route(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
  const method = (typeof input === 'object' && 'method' in input ? input.method : init?.method) ?? 'GET';

  if (url.includes('/chat/messages') && url.endsWith('/stream')) {
    return Promise.resolve(sse(ANSWER_FRAMES));
  }
  if (url.includes('/chat/messages') && method === 'POST') {
    return Promise.resolve(
      json({
        user_message: {
          id: 'user-message',
          role: 'user',
          status: 'done',
          content: "What's the total spend across all vendor contracts?",
        },
        message_id: MESSAGE,
        stream_url: `/api/v1/workspaces/${WORKSPACE}/chat/messages/${MESSAGE}/stream`,
      }),
    );
  }
  if (url.includes('/chat/messages')) return Promise.resolve(json({ messages: [] }));
  if (url.includes('/chat/suggestions')) {
    return Promise.resolve(json({ questions: ['Which vendor did we spend most with?'] }));
  }
  if (url.endsWith('/events')) {
    // An open, silent stream, which is what a settled workspace looks like.
    return Promise.resolve(sse([]));
  }
  if (url.includes('/documents/doc-1/pages/')) {
    return Promise.resolve(new Response('', { status: 404 }));
  }
  if (url.includes('/documents/doc-1')) {
    return Promise.resolve(
      json({
        id: 'doc-1',
        filename: 'contract_v2.pdf',
        pages: [{ index: 3, width_pt: 612, height_pt: 792 }],
      }),
    );
  }
  return Promise.resolve(
    json({
      id: WORKSPACE,
      label: 'Q3 Vendor Contracts',
      documents: [
        { id: 'doc-1', filename: 'contract_v2.pdf', status: 'done' },
        { id: 'doc-2', filename: 'vendor_terms.docx', status: 'done' },
      ],
    }),
  );
}

beforeEach(() => {
  window.localStorage.setItem(`distill.token.${WORKSPACE}`, 'tok_test');
  fetchMock.mockReset();
  fetchMock.mockImplementation(route);
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

async function ask() {
  const user = userEvent.setup();
  renderScreen();

  const box = await screen.findByRole('textbox', { name: /ask about these documents/i });
  await user.type(box, "What's the total spend across all vendor contracts?");
  await user.click(screen.getByRole('button', { name: /send question/i }));
  return user;
}

describe('ChatScreen', () => {
  it('offers generated questions on an empty conversation', async () => {
    renderScreen();

    expect(
      await screen.findByRole('button', { name: /which vendor did we spend most with/i }),
    ).toBeInTheDocument();
  });

  it('puts a suggested question in the box rather than sending it', async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(
      await screen.findByRole('button', { name: /which vendor did we spend most with/i }),
    );

    // It is a starting point, not a decision: the question should be editable first.
    expect(screen.getByRole('textbox', { name: /ask about these documents/i })).toHaveValue(
      'Which vendor did we spend most with?',
    );
    expect(
      fetchMock.mock.calls.filter(([input]) => {
        const url = typeof input === 'string' ? input : (input as Request).url;
        return url.includes('/chat/messages') && !url.endsWith('/stream');
      }).length,
    ).toBeLessThanOrEqual(1);
  });

  it('names what it read before any prose exists', async () => {
    await ask();

    // Requirement 3.2: the sources are sent early precisely so the wait shows progress.
    expect(await screen.findByText(/read 2 passages from 2 documents/i)).toBeInTheDocument();
    expect(screen.getAllByText('contract_v2.pdf').length).toBeGreaterThan(0);
  });

  it('streams the prose and renders figures the server computed', async () => {
    await ask();

    await waitFor(() =>
      expect(screen.getByText(/total spend is \$501,650/i)).toBeInTheDocument(),
    );

    // Product principle 5: the bar labels and figures are read out of the surface's data
    // model by path, so they are the server's numbers, not the model's.
    expect(screen.getByText('Spend by vendor (Q3)')).toBeInTheDocument();
    expect(screen.getByText('Argosy Logistics')).toBeInTheDocument();
    expect(screen.getByText('184,200 USD')).toBeInTheDocument();
  });

  it('turns a citation marker into a control that opens the source', async () => {
    const user = await ask();

    const marker = await screen.findByRole('button', { name: /show source 1/i });
    await user.click(marker);

    const viewer = await screen.findByRole('complementary', { name: /source viewer/i });
    expect(within(viewer).getByText(/september surcharge added \$31,400/i)).toBeVisible();
    expect(within(viewer).getByText(/contract_v2\.pdf · p\. 4/i)).toBeInTheDocument();
  });

  it('says a page could not be rendered rather than showing an empty frame', async () => {
    const user = await ask();

    await user.click(await screen.findByRole('button', { name: /show source 1/i }));

    const viewer = await screen.findByRole('complementary', { name: /source viewer/i });
    expect(
      await within(viewer).findByText(/has not been rendered/i),
    ).toBeInTheDocument();
  });

  it('reattaches to an answer that was still being written', async () => {
    /*
     * A refresh mid-answer. Generation does not depend on anyone listening (decision D32),
     * so the persisted row says `streaming` with empty content and the buffer is still
     * there to be tailed. Without reattachment the message would sit blank forever.
     */
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      const method =
        (typeof input === 'object' && 'method' in input ? input.method : init?.method) ??
        'GET';
      if (url.includes('/chat/messages') && !url.endsWith('/stream') && method === 'GET') {
        return Promise.resolve(
          json({
            messages: [
              { id: 'u1', role: 'user', status: 'done', content: 'An earlier question' },
              { id: MESSAGE, role: 'assistant', status: 'streaming', content: '' },
            ],
          }),
        );
      }
      return route(input, init);
    });

    renderScreen();

    expect(await screen.findByText('An earlier question')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/total spend is \$501,650/i)).toBeInTheDocument(),
    );
  });
});
