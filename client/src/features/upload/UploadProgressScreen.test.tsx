import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Providers } from '../../app/Providers';
import { makeQueryClient } from '../../app/queryClient';
import { UploadProgressScreen } from './UploadProgressScreen';
import { usePendingUploads } from './pendingUploads';

/**
 * The screen that holds a person while their bytes are in flight.
 *
 * The first test here exists because of a specific failure: the screen originally selected
 * from the pending-uploads store with `state.workspaceId === id ? state.files : []`, which
 * allocates a new array on every miss. Zustand compares snapshots by reference, so React
 * re-rendered until it threw "Maximum update depth exceeded" and the page went blank. The
 * whole suite passed throughout, because nothing rendered this component. Rendering it —
 * in both the staged and the empty case — is the assertion that matters.
 */

const WORKSPACE = '33333333-3333-4333-8333-333333333333';

function renderAt(path = `/w/${WORKSPACE}/upload`) {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/w/:workspaceId/upload" element={<UploadProgressScreen />} />
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

beforeEach(() => {
  window.localStorage.setItem(`distill.token.${WORKSPACE}`, 'tok_test');
  usePendingUploads.getState().clear();

  // The screen sends through XHR and reads the workspace through fetch; neither should
  // reach a real network in a test.
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ label: 'Q3 Vendor Contracts', documents: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
  vi.stubGlobal(
    'XMLHttpRequest',
    class {
      upload = { addEventListener: () => {} };
      addEventListener = () => {};
      open = () => {};
      setRequestHeader = () => {};
      send = () => {};
      status = 200;
      response = null;
      responseType = '';
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('UploadProgressScreen', () => {
  it('renders without looping when the store holds nothing for this workspace', async () => {
    renderAt();

    expect(
      await screen.findByRole('heading', { name: /your documents are in/i }),
    ).toBeInTheDocument();
  });

  it('lists a row per staged file and holds Continue while they are in flight', async () => {
    usePendingUploads
      .getState()
      .stage(WORKSPACE, [makeFile('invoice_0417.pdf'), makeFile('notes.txt')], []);

    const { container } = renderAt();

    expect(
      await screen.findByRole('heading', { name: /uploading your documents/i }),
    ).toBeInTheDocument();

    /*
     * Each filename appears more than once: on its row, and on however many cards the
     * spiral needed to close its ring. The row is the one that has to be there, so it is
     * the one asserted — by its progress bar's accessible name, which no card carries.
     */
    const rows = container.querySelectorAll('progress[aria-label*="."]');
    const rowLabels = Array.from(rows, (bar) => bar.getAttribute('aria-label') ?? '');
    expect(rowLabels.some((label) => label.startsWith('invoice_0417.pdf: '))).toBe(true);
    expect(rowLabels.some((label) => label.startsWith('notes.txt: '))).toBe(true);

    expect(screen.getAllByText('invoice_0417.pdf').length).toBeGreaterThan(0);

    // The point of the screen: there is nothing worth doing with a document the server has
    // not received, so the way forward stays shut until the bytes land.
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled();
  });

  it('answers "how much longer" once, above the per-file detail', async () => {
    usePendingUploads
      .getState()
      .stage(WORKSPACE, [makeFile('invoice_0417.pdf'), makeFile('notes.txt')], []);

    renderAt();

    // The aggregate is what a person waiting actually wants; the rows are the audit trail.
    expect(await screen.findByText(/0 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/documents arrived/)).toBeInTheDocument();
    expect(screen.getByText(/see every file/i)).toBeInTheDocument();
  });

  it('keeps the spiral out of the accessibility tree, since the rows say the same thing', async () => {
    usePendingUploads.getState().stage(WORKSPACE, [makeFile('invoice_0417.pdf')], []);

    const { container } = renderAt();
    await screen.findByRole('heading', { name: /uploading your documents/i });

    // Decorative: a screen reader that walked ten repeated cards would learn nothing the
    // list below does not already say, at ten times the length.
    const ring = container.querySelector('[aria-hidden="true"]');
    expect(ring).not.toBeNull();
    expect(screen.getAllByText('invoice_0417.pdf').length).toBeGreaterThan(1);
  });

  it('takes the staged files so a remount does not upload them twice', async () => {
    usePendingUploads.getState().stage(WORKSPACE, [makeFile('invoice_0417.pdf')], []);

    renderAt();

    await waitFor(() => expect(usePendingUploads.getState().files).toHaveLength(0));
  });

  it('names the workspace in the header once the overview arrives', async () => {
    renderAt();

    expect(await screen.findByText('Q3 Vendor Contracts')).toBeInTheDocument();
  });
});
