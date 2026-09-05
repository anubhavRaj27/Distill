import { FileText, Image, Sheet, Trash2 } from 'lucide-react';
import { useState } from 'react';
import styled from 'styled-components';

import type { components } from '../../api/schema';
import { formatBytes } from '../../lib/files';
import type { DocumentProgress } from '../processing/useDocumentProgress';

/**
 * Every file in the workspace, with what became of it. Decision D71.
 *
 * The Upload screen used to be a wait: it narrated files leaving this browser and then had
 * nothing to say. Come back later and it told you "this browser is not uploading anything
 * right now" about a workspace holding ten documents. So the wait is now the transient part
 * and this list is the screen — the one place that answers "what is in here", which is the
 * question a person asks before they trust a table built out of it.
 *
 * Three things it deliberately shows that the processing strip does not:
 *
 * - **The format the parser actually used**, not the extension. A `.csv` that was really a
 *   tab-separated export, or a `.pdf` that is a scan, is exactly the case worth seeing, and
 *   the extension would hide it.
 * - **Documents that finished.** The strip is about what is still moving and disappears when
 *   everything settles, which is right for a strip above a conversation and useless as an
 *   inventory.
 * - **A way out.** Open it, or delete it (requirement FR-07), which until now had a route on
 *   the server and no way to reach it.
 */

type DocumentSummary = components['schemas']['DocumentSummary'];

/** A document as this list needs it: the stored row, with any live stage laid over it. */
export interface LibraryDocument extends DocumentSummary {
  liveStatus?: DocumentProgress['status'];
  liveStageDetail?: string | null;
  liveFailureReason?: string | null;
}

const List = styled.ul`
  display: flex;
  flex-direction: column;
  width: 100%;
  margin: 0;
  padding: 0;
  list-style: none;

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  overflow: hidden;
`;

const Row = styled.li`
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: ${({ theme }) => theme.space.md};
  padding: ${({ theme }) => theme.space.md} ${({ theme }) => theme.space.lg};

  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  &:last-child {
    border-bottom: 0;
  }

  &[data-failed='true'] {
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

const Glyph = styled.span`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: ${({ theme }) => theme.color.inkMuted};

  [data-failed='true'] & {
    color: ${({ theme }) => theme.tier.conflict.color};
  }
`;

const Middle = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
`;

const Name = styled.span`
  font-size: 13px;
  color: ${({ theme }) => theme.color.ink};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Meta = styled.span`
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: ${({ theme }) => theme.space.sm};
  font-size: 12px;
  line-height: 1.5;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Stage = styled.span`
  font-variant: small-caps;
  letter-spacing: 0.02em;

  &[data-state='failed'] {
    color: ${({ theme }) => theme.tier.conflict.color};
    font-variant: normal;
    letter-spacing: 0;
  }

  &[data-state='working'] {
    color: ${({ theme }) => theme.color.ink};
  }
`;

const Format = styled.span`
  font-family: ${({ theme }) => theme.font.mono};
  font-size: 10px;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: ${({ theme }) => theme.color.paperSunken};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

const Actions = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
`;

const RowButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;

  font-family: inherit;
  font-size: 12px;
  color: ${({ theme }) => theme.color.ink};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.paperSunken};
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }

  &[data-danger='true'] {
    color: ${({ theme }) => theme.tier.conflict.color};
    border-color: ${({ theme }) => theme.tier.conflict.color};
  }
`;

const Empty = styled.p`
  width: 100%;
  margin: 0;
  padding: ${({ theme }) => theme.space.xl};
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
  text-align: center;

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px dashed ${({ theme }) => theme.color.lineStrong};
  border-radius: ${({ theme }) => theme.radius.md};
`;

/**
 * The same words the processing strip uses. One vocabulary for one set of states: a person
 * who read "pulling out values" above their conversation should not meet "extracting" here
 * and have to work out that they are the same thing.
 */
const STAGE_WORDS: Record<string, string> = {
  uploaded: 'queued',
  parsing: 'reading the file',
  extracting: 'pulling out values',
  indexing: 'making it searchable',
  done: 'ready',
  failed: 'failed',
};

const FORMAT_WORDS: Record<string, string> = {
  pdf: 'PDF',
  docx: 'DOCX',
  xlsx: 'XLSX',
  csv: 'CSV',
  text: 'TEXT',
  image: 'IMAGE',
};

function glyphFor(format: string) {
  if (format === 'image') return Image;
  if (format === 'xlsx' || format === 'csv') return Sheet;
  return FileText;
}

/** Pages, or nothing at all. "0 pages" on a document still being read is a lie. */
function pagesLabel(pageCount: number | null | undefined): string | null {
  if (!pageCount) return null;
  return pageCount === 1 ? '1 page' : `${pageCount} pages`;
}

export interface DocumentLibraryProps {
  documents: LibraryDocument[];
  /** Opens the file in the source viewer. */
  onOpen: (document: LibraryDocument) => void;
  onDelete: (document: LibraryDocument) => void;
  /** The document currently being deleted, so its row can say so. */
  deletingId?: string | null;
  isPending?: boolean;
}

export function DocumentLibrary({
  documents,
  onOpen,
  onDelete,
  deletingId = null,
  isPending = false,
}: DocumentLibraryProps) {
  /*
   * Deleting takes a document's extracted row, its passages and every citation pointing at
   * it, and there is no undo. So the button asks once, in place: a second click on the same
   * row confirms. A dialog would be heavier for the same guarantee, and an undo toast would
   * mean keeping deleted rows around to restore.
   */
  const [confirming, setConfirming] = useState<string | null>(null);

  if (documents.length === 0) {
    return (
      <Empty>
        {isPending
          ? 'Looking at what this workspace holds…'
          : 'No documents yet. Drop files here or use “Add more files” above.'}
      </Empty>
    );
  }

  return (
    <List aria-label="Documents in this workspace">
      {documents.map((document) => {
        const status = document.liveStatus ?? document.status;
        const failed = status === 'failed';
        const settled = status === 'done' || failed;
        const detail = failed
          ? (document.liveFailureReason ?? document.failure_reason)
          : (document.liveStageDetail ?? document.stage_detail);
        const Icon = glyphFor(document.source_format);
        const isConfirming = confirming === document.id;
        const isDeleting = deletingId === document.id;

        return (
          <Row key={document.id} data-failed={failed}>
            <Glyph>
              <Icon size={16} aria-hidden="true" />
            </Glyph>

            <Middle>
              <Name title={document.filename}>{document.filename}</Name>
              <Meta>
                {/*
                  Omitted rather than shown empty when the server did not say. Guessing it
                  from the extension here would undo the point of showing it at all.
                */}
                {document.source_format && (
                  <Format>{FORMAT_WORDS[document.source_format] ?? document.source_format}</Format>
                )}
                <Stage data-state={failed ? 'failed' : settled ? 'ready' : 'working'}>
                  {STAGE_WORDS[status] ?? status}
                </Stage>
                {pagesLabel(document.page_count) && <span>{pagesLabel(document.page_count)}</span>}
                <span>{formatBytes(document.size_bytes)}</span>
                {/*
                  The stage detail is the server's own sentence — "scanned image detected,
                  running text recognition", or why a file failed. It is the difference
                  between a person waiting and a person wondering whether it is stuck.
                */}
                {detail && <span>{detail}</span>}
              </Meta>
            </Middle>

            <Actions>
              <RowButton
                type="button"
                onClick={() => onOpen(document)}
                disabled={!settled || failed}
                title={
                  failed
                    ? 'This file could not be read'
                    : settled
                      ? undefined
                      : 'Still being read'
                }
              >
                Open
              </RowButton>

              <RowButton
                type="button"
                data-danger={isConfirming}
                disabled={isDeleting}
                aria-label={
                  isConfirming
                    ? `Confirm deleting ${document.filename}`
                    : `Delete ${document.filename}`
                }
                onClick={() => {
                  if (isConfirming) {
                    setConfirming(null);
                    onDelete(document);
                  } else {
                    setConfirming(document.id);
                  }
                }}
                onBlur={() => setConfirming((current) => (current === document.id ? null : current))}
              >
                <Trash2 size={13} aria-hidden="true" />
                {isDeleting ? 'Deleting…' : isConfirming ? 'Confirm' : 'Delete'}
              </RowButton>
            </Actions>
          </Row>
        );
      })}
    </List>
  );
}
