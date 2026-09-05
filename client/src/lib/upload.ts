/**
 * Uploading documents with per-file progress.
 *
 * This is the one place in the client that does not use the generated `openapi-fetch`
 * client, and the reason is a hard platform limitation rather than a preference: **`fetch`
 * cannot report upload progress**. There is no event, no callback, and no readable stream
 * on the request side in any shipping browser. `XMLHttpRequest` can, through
 * `xhr.upload.onprogress`, so a screen that shows a bar filling has to use it.
 *
 * The second consequence is one request per file. A single multipart body carrying six
 * files reports one byte counter for the whole body, and there is no way to attribute those
 * bytes back to individual files — the bars would all have to move together, which is not
 * what the screen promises. One request per file also isolates failure: a rejected scan
 * does not take the other five with it.
 *
 * The cost is N requests instead of one, bounded by the server's own limit of 25 files per
 * upload, and mitigated by a small concurrency window.
 */

import type { components } from '../api/schema';

type UploadResponse = components['schemas']['UploadResponse'];

/** How many files are in flight at once. Enough to saturate a connection, not enough to
 * starve each other's progress reporting into uselessness. */
const CONCURRENCY = 3;

export type UploadPhase = 'waiting' | 'sending' | 'ready' | 'failed';

export interface UploadTask {
  /** Stable across the batch. Files have no identity of their own, so we mint one. */
  readonly key: string;
  readonly file: File;
  phase: UploadPhase;
  /** Bytes confirmed sent. */
  sent: number;
  /** The server's identifier, once it has one. */
  documentId?: string;
  /** Present when `phase` is `failed`. A sentence, ready to render. */
  error?: string;
}

export function makeTasks(files: readonly File[]): UploadTask[] {
  return files.map((file, index) => ({
    key: `${index}-${file.name}-${file.size}`,
    file,
    phase: 'waiting',
    sent: 0,
  }));
}

export interface UploadOutcome {
  documentId?: string;
  error?: string;
}

/**
 * Send one file. Resolves with the outcome rather than rejecting, because a file the server
 * refuses is a normal result this screen has to render, not an exception.
 */
export function sendOne(options: {
  baseUrl: string;
  workspaceId: string;
  token: string;
  file: File;
  onProgress: (sent: number) => void;
  signal?: AbortSignal;
}): Promise<UploadOutcome> {
  const { baseUrl, workspaceId, token, file, onProgress, signal } = options;

  return new Promise<UploadOutcome>((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${baseUrl}/api/v1/workspaces/${workspaceId}/documents`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.responseType = 'json';

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(event.loaded);
    });

    xhr.addEventListener('load', () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        resolve({ error: readError(xhr) });
        return;
      }

      // A single-file request yields either one acceptance or one rejection. The server
      // reports refusals in the body with a 200, because a mixed batch is the normal case.
      const body = xhr.response as UploadResponse | null;
      const accepted = body?.accepted?.[0];
      if (accepted) {
        resolve({ documentId: accepted.id });
        return;
      }

      const rejected = body?.rejected?.[0];
      resolve({
        error: rejected?.message ?? 'The server did not accept this file.',
      });
    });

    xhr.addEventListener('error', () => {
      resolve({ error: 'The connection dropped while sending this file.' });
    });

    xhr.addEventListener('timeout', () => {
      resolve({ error: 'Sending this file timed out.' });
    });

    xhr.addEventListener('abort', () => {
      resolve({ error: 'Upload cancelled.' });
    });

    signal?.addEventListener('abort', () => xhr.abort(), { once: true });

    const form = new FormData();
    form.append('files', file);
    xhr.send(form);
  });
}

function readError(xhr: XMLHttpRequest): string {
  const body = xhr.response as { detail?: unknown; message?: unknown } | null;
  const detail = body?.detail ?? body?.message;
  if (typeof detail === 'string') return detail;
  if (xhr.status === 413) return 'This file is larger than the server accepts.';
  return `The server refused this file (${xhr.status}).`;
}

/**
 * Run a batch, at most `CONCURRENCY` at a time, reporting every change through `onChange`.
 *
 * Workers pull from a shared cursor rather than the batch being sliced into fixed groups,
 * so one slow 20 MB scan does not hold up the small files queued behind it.
 */
export async function runBatch(options: {
  baseUrl: string;
  workspaceId: string;
  token: string;
  tasks: UploadTask[];
  onChange: (key: string, patch: Partial<UploadTask>) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const { tasks, onChange, ...rest } = options;
  let cursor = 0;

  async function worker(): Promise<void> {
    for (;;) {
      const index = cursor++;
      const task = tasks[index];
      if (!task) return;
      if (options.signal?.aborted) return;

      onChange(task.key, { phase: 'sending', sent: 0 });

      const outcome = await sendOne({
        ...rest,
        file: task.file,
        onProgress: (sent) => onChange(task.key, { sent }),
      });

      onChange(
        task.key,
        outcome.documentId
          ? { phase: 'ready', sent: task.file.size, documentId: outcome.documentId }
          : { phase: 'failed', error: outcome.error },
      );
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, tasks.length) }, () => worker()),
  );
}
