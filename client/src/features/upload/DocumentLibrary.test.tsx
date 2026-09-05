import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from 'styled-components';
import { describe, expect, it, vi } from 'vitest';

import { theme } from '../../ui/theme';
import { DocumentLibrary, type LibraryDocument } from './DocumentLibrary';

/**
 * The list that answers "what is actually in this workspace". Decision D71.
 *
 * Three things it has to get right, and each is here because getting it wrong is quiet
 * rather than loud: a document still being read must not offer to open, a deletion must be
 * asked for twice, and a live stage must win over the snapshot the page loaded with.
 */

function makeDocument(overrides: Partial<LibraryDocument> = {}): LibraryDocument {
  return {
    id: 'doc-1',
    filename: 'acme-invoice-2041.pdf',
    status: 'done',
    stage_detail: null,
    failure_reason: null,
    page_count: 2,
    size_bytes: 41_000,
    created_at: '2026-09-06T09:00:00Z',
    source_format: 'pdf',
    ...overrides,
  };
}

function renderLibrary(documents: LibraryDocument[]) {
  const onOpen = vi.fn();
  const onDelete = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <DocumentLibrary documents={documents} onOpen={onOpen} onDelete={onDelete} />
    </ThemeProvider>,
  );
  return { onOpen, onDelete };
}

describe('DocumentLibrary', () => {
  it('shows what a document is, not what its name ends in', () => {
    /*
     * The format comes from the server's sniffing, so a file whose extension lies still
     * reports what was actually parsed. That is the case worth seeing at all.
     */
    renderLibrary([
      makeDocument({ filename: 'export.csv', source_format: 'xlsx', page_count: 1 }),
    ]);

    expect(screen.getByText('export.csv')).toBeInTheDocument();
    expect(screen.getByText('XLSX')).toBeInTheDocument();
    expect(screen.getByText('1 page')).toBeInTheDocument();
  });

  it('prefers the live stage over the snapshot the page loaded with', () => {
    renderLibrary([
      makeDocument({ status: 'uploaded', liveStatus: 'extracting', liveStageDetail: 'page 2 of 3' }),
    ]);

    expect(screen.getByText('pulling out values')).toBeInTheDocument();
    expect(screen.getByText('page 2 of 3')).toBeInTheDocument();
    expect(screen.queryByText('queued')).not.toBeInTheDocument();
  });

  it('will not offer to open a document that is still being read', () => {
    renderLibrary([makeDocument({ status: 'parsing' })]);
    expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled();
  });

  it('shows the reason a document failed, and does not offer to open it', () => {
    renderLibrary([
      makeDocument({
        status: 'failed',
        failure_reason: 'This PDF is password protected.',
      }),
    ]);

    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('This PDF is password protected.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled();
  });

  it('asks before deleting, because there is no undo', async () => {
    const user = userEvent.setup();
    const { onDelete } = renderLibrary([makeDocument()]);

    await user.click(screen.getByRole('button', { name: 'Delete acme-invoice-2041.pdf' }));
    expect(onDelete).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole('button', { name: 'Confirm deleting acme-invoice-2041.pdf' }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete.mock.calls[0]?.[0].id).toBe('doc-1');
  });

  it('opens the document it was asked to open', async () => {
    const user = userEvent.setup();
    const { onOpen } = renderLibrary([makeDocument()]);

    await user.click(screen.getByRole('button', { name: 'Open' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0]?.[0].filename).toBe('acme-invoice-2041.pdf');
  });

  it('says the workspace is empty rather than showing an empty box', () => {
    renderLibrary([]);
    expect(screen.getByText(/no documents yet/i)).toBeInTheDocument();
  });
});
