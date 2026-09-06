import type { DocumentProgress } from './useDocumentProgress';

/**
 * What each pipeline stage is called, in one place.
 *
 * There were three copies of this by September 6, 2026 — the processing strip, the document
 * library, and the upload rows — which is three chances for a person to read "extracting"
 * on one screen and "pulling out values" on another and wonder whether they are the same
 * thing. They are the same thing, and now they are the same string.
 *
 * The words describe what is happening TO the document, not the name of the stage in the
 * pipeline. Nobody outside this codebase knows what indexing is; everybody understands
 * "making it searchable".
 */
export const STAGE_WORDS: Record<string, string> = {
  uploaded: 'queued',
  parsing: 'reading the file',
  extracting: 'pulling out values',
  indexing: 'making it searchable',
  done: 'ready',
  failed: 'failed',
};

export function stageWord(status: string): string {
  return STAGE_WORDS[status] ?? status;
}

/** Whether the server has finished with this document, one way or the other. */
export function isSettled(status: DocumentProgress['status'] | string): boolean {
  return status === 'done' || status === 'failed';
}
