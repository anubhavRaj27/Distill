import { useEffect, useMemo, useState } from 'react';

import { authHeader } from '../../api/client';
import { consumeSse } from '../../lib/sse';

/**
 * Live document status, from the workspace event stream. Requirement FR-04.
 *
 * A second SSE endpoint, separate from the per-answer one and separate on purpose: this is
 * durable, workspace-wide and resumable from a persisted log, where an answer stream is
 * ephemeral and belongs to one message. They share `lib/sse` and nothing else.
 *
 * The upload screen hands over as soon as bytes have arrived (decision D36), so parsing,
 * extraction and indexing are still running when Chat opens. This is what narrates that,
 * and it is why the chat screen is usable during it rather than gated behind it.
 */

export type DocumentStage =
  | 'uploaded'
  | 'parsing'
  | 'extracting'
  | 'indexing'
  | 'done'
  | 'failed';

export interface DocumentProgress {
  documentId: string;
  filename: string;
  status: DocumentStage;
  stageDetail: string | null;
  failureReason: string | null;
}

const BASE_URL = import.meta.env.VITE_API_URL ?? '';

interface StatusPayload {
  type?: unknown;
  document_id?: unknown;
  filename?: unknown;
  status?: unknown;
  stage_detail?: unknown;
  failure_reason?: unknown;
}

/**
 * Follow the workspace stream, keeping the latest status per document.
 *
 * `seed` primes the map from the workspace overview, so a page loaded after everything
 * finished shows the finished state rather than nothing: the stream reports transitions,
 * and a document that is already done will not transition again.
 */
export function useDocumentProgress(
  workspaceId: string,
  token: string | null,
  seed: { id: string; filename: string; status: string }[],
): DocumentProgress[] {
  const [live, setLive] = useState<Record<string, DocumentProgress>>({});

  useEffect(() => {
    if (!token) return;

    const controller = new AbortController();

    void consumeSse({
      url: `${BASE_URL}/api/v1/workspaces/${workspaceId}/events`,
      headers: authHeader(token),
      signal: controller.signal,
      onMessage: (frame) => {
        if (!frame.data) return;

        let payload: StatusPayload;
        try {
          payload = JSON.parse(frame.data) as StatusPayload;
        } catch {
          return;
        }

        // Heartbeats, record upserts, schema updates and dashboard status all arrive here.
        // The strip cares about one of them.
        if (payload.type !== 'document.status') return;
        if (typeof payload.document_id !== 'string') return;

        const entry: DocumentProgress = {
          documentId: payload.document_id,
          filename: typeof payload.filename === 'string' ? payload.filename : '',
          status: (typeof payload.status === 'string'
            ? payload.status
            : 'uploaded') as DocumentStage,
          stageDetail:
            typeof payload.stage_detail === 'string' ? payload.stage_detail : null,
          failureReason:
            typeof payload.failure_reason === 'string' ? payload.failure_reason : null,
        };

        setLive((current) => ({ ...current, [entry.documentId]: entry }));
      },
    }).catch(() => {
      /*
       * Swallowed on purpose. The strip is progress narration, not the product: a stream
       * that will not stay up means the strip stops updating, while the conversation and
       * every already-indexed document carry on working. The seed below still reports the
       * last state the overview knew about.
       */
    });

    return () => controller.abort();
  }, [token, workspaceId]);

  return useMemo(() => {
    const merged = new Map<string, DocumentProgress>();
    for (const document of seed) {
      merged.set(document.id, {
        documentId: document.id,
        filename: document.filename,
        status: document.status as DocumentStage,
        stageDetail: null,
        failureReason: null,
      });
    }
    // The stream wins over the seed: it is newer by construction.
    for (const [id, entry] of Object.entries(live)) merged.set(id, entry);
    return [...merged.values()];
  }, [live, seed]);
}
