import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Providers } from '../../app/Providers';
import { makeQueryClient } from '../../app/queryClient';
import { FirstRunScreen } from './FirstRunScreen';
import { usePendingUploads } from './pendingUploads';

/**
 * The first-run screen has one job: a person who has never seen this product understands
 * it and can start in one action. These tests hold that job in place — the promise in the
 * headline, both ways in being equally reachable, and a refused file being explained
 * rather than swallowed.
 *
 * Network is stubbed at `fetch` rather than with MSW. This screen makes exactly two calls
 * and the assertions are about what the interface does, not about response shapes; MSW
 * earns its place with the workspace shell, where handlers get reused across features.
 */

function renderScreen() {
  return render(
    <Providers queryClient={makeQueryClient()}>
      <MemoryRouter>
        <FirstRunScreen />
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
  // The prompt text sits directly inside the element carrying the drop handlers.
  const zone = screen.getByText(/drag files here/i).parentElement!;
  fireEvent.drop(zone, { dataTransfer: { files, types: ['Files'] } });
}

const fetchMock = vi.fn();

beforeEach(() => {
  usePendingUploads.getState().clear();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The nth request the client actually issued. */
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

describe('FirstRunScreen', () => {
  it('names itself and states what it does before anything has been uploaded', () => {
    renderScreen();

    // The name is drawn as particles on a canvas, so the accessible name has to come from
    // real text underneath it. Querying by role is what proves the text is actually there.
    expect(screen.getByRole('heading', { name: 'Distill' })).toBeInTheDocument();
    expect(screen.getByText(/pull out what matters/i)).toBeInTheDocument();
  });

  it('offers both ways in, neither buried behind the other', () => {
    renderScreen();

    expect(screen.getByRole('button', { name: /choose files/i })).toBeEnabled();
    expect(
      screen.getByRole('button', { name: /try with sample documents/i }),
    ).toBeEnabled();
  });

  it('shows no application chrome, because there is nothing yet to navigate to', () => {
    renderScreen();

    // Decision D57: the header is workspace chrome. Before an upload, Chat and Data lead
    // nowhere, so the screen is the product's front door and nothing else.
    expect(screen.queryByRole('banner')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByText('Chat')).not.toBeInTheDocument();
    expect(screen.queryByText('Data')).not.toBeInTheDocument();
  });

  it('gives the file input an accessible name that lists what it accepts', () => {
    renderScreen();

    const input = screen.getByLabelText(/choose documents to upload/i);
    expect(input).toHaveAttribute('accept', expect.stringContaining('.pdf'));
    expect(input).toHaveAttribute('multiple');
  });

  it('refuses an unsupported file inline and never contacts the server', async () => {
    renderScreen();

    drop([makeFile('slides.key')]);

    const notice = await screen.findByRole('status');
    expect(within(notice).getByText(/slides\.key/)).toBeInTheDocument();
    expect(within(notice).getByText(/cannot read \.key files/i)).toBeInTheDocument();

    // Requirement FR-03: rejected before upload begins, not after a round trip.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('carries a mixed selection onward, refusals included', async () => {
    respondOnce({
      id: '11111111-1111-4111-8111-111111111111',
      token: 'tok_test',
      created_at: new Date().toISOString(),
    });

    renderScreen();

    drop([makeFile('invoice.pdf'), makeFile('slides.key')]);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    // openapi-fetch hands a fully built `Request` to the transport, not (url, init).
    expect(requestAt(0).url).toContain('/api/v1/workspaces');

    // The acceptable file is not uploaded from here: the upload screen owns the transfer,
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
    respondOnce({
      id: '22222222-2222-4222-8222-222222222222',
      token: 'tok_test',
      created_at: new Date().toISOString(),
    });
    respondOnce({ documents: [] });

    renderScreen();
    await user.click(screen.getByRole('button', { name: /try with sample documents/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const seed = requestAt(1);
    expect(seed.url).toContain('/documents/seed');
    expect(seed.method).toBe('POST');
    expect(seed.headers.get('authorization')).toBe('Bearer tok_test');
  });

  it('explains a failure to start instead of leaving the screen inert', async () => {
    const user = userEvent.setup();
    respondOnce({ detail: 'The database is not reachable.', correlation_id: 'req-42' }, 503);

    renderScreen();
    await user.click(screen.getByRole('button', { name: /try with sample documents/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/database is not reachable/i);
    // The correlation id is what turns "it broke" into a traceable bug report.
    expect(alert).toHaveTextContent('req-42');
  });
});
