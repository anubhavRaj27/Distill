import type { components } from '../../api/schema';
import type { SseMessage } from '../../lib/sse';

/**
 * The per-answer stream vocabulary, mirroring `server/app/chat/events.py`, and the reducer
 * that folds it into what the screen draws.
 *
 * These types are hand-written rather than generated, and that is the one place in the
 * client where a shape is not taken from the OpenAPI document. The reason is structural:
 * the stream's payloads never appear in a response body, so FastAPI never puts them in the
 * schema. `MessageResponse` — what `done` carries and what history returns — IS generated,
 * and is imported below, so the half that can be checked against the server is.
 *
 * **Ordering is part of the server's contract** and this reducer relies on it:
 * `visual` or `visual_skipped` always precedes the first `token`, and a `citation` always
 * precedes the token carrying its marker. So the reducer never has to render an
 * unresolved footnote and rewrite it later, and never has to reflow prose around a card
 * that arrives late (decisions D45 and D47).
 */

export type ChatMessage = components['schemas']['MessageResponse'];

export type AnswerStage =
  | 'retrieving'
  | 'reading'
  | 'planning'
  | 'answering'
  | 'done'
  | 'stopped'
  | 'failed';

export type VisualKind = 'metric' | 'bar' | 'line' | 'table';

export interface SourceRef {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_index: number | null;
  is_digest: boolean;
}

/**
 * A highlight rectangle, exactly as `server/app/domain/geometry.py` sends one.
 *
 * The vertical edges are `top` and `bottom`, not `y0`/`y1`, and the origin is the TOP of
 * the page — which happens to match CSS, so no flip is needed anywhere. Units are page
 * points; the viewer scales them by the rendered width over `width_pt`.
 */
export interface BBox {
  x0: number;
  top: number;
  x1: number;
  bottom: number;
}

export interface Citation {
  n: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page_index: number | null;
  boxes: BBox[];
  excerpt: string;
}

/** One A2UI protocol message. Shaped loosely here; `features/a2ui` narrows it. */
export type SurfaceMessage = Record<string, unknown>;

export type AnswerEvent =
  | { type: 'status'; stage: AnswerStage; detail?: string | null }
  | { type: 'sources'; sources: SourceRef[] }
  | { type: 'visual'; kind: VisualKind; title: string; surface: SurfaceMessage[] }
  | {
      type: 'visual_skipped';
      reason: 'none_planned' | 'empty_result' | 'degenerate_result' | 'evaluation_failed';
    }
  | { type: 'token'; text: string }
  | ({ type: 'citation' } & Citation)
  | { type: 'done'; message: ChatMessage }
  | { type: 'error'; message: string; correlation_id?: string | null };

/**
 * Turn a raw SSE frame into an event, or null.
 *
 * Null rather than throwing for anything unrecognised: a heartbeat, a comment, or an event
 * type added by a newer server all reach here, and none of them is a reason to tear down a
 * half-written answer. The `type` inside the payload is trusted over the SSE `event:` name
 * because the server derives the latter from the former.
 */
export function parseAnswerEvent(frame: SseMessage): AnswerEvent | null {
  if (!frame.data) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(frame.data);
  } catch {
    return null;
  }

  if (!payload || typeof payload !== 'object') return null;
  const type = (payload as { type?: unknown }).type;
  if (typeof type !== 'string') return null;

  switch (type) {
    case 'status':
    case 'sources':
    case 'visual':
    case 'visual_skipped':
    case 'token':
    case 'citation':
    case 'done':
    case 'error':
      return payload as AnswerEvent;
    default:
      return null;
  }
}

/** What the screen draws for an answer that is still arriving. */
export interface LiveAnswer {
  messageId: string;
  stage: AnswerStage;
  sources: SourceRef[];
  visual: { kind: VisualKind; title: string; surface: SurfaceMessage[] } | null;
  /**
   * True until the server has said whether there is a card. The card's space is reserved
   * during that window and released on `visual_skipped`, so prose never starts under a
   * placeholder that then vanishes.
   */
  awaitingVisual: boolean;
  text: string;
  citations: Citation[];
  /** Set when the stream is retrying, so the interface can say so rather than freezing. */
  reconnecting: boolean;
  error: string | null;
  /** The persisted message, once `done` has arrived. Authoritative over everything above. */
  finished: ChatMessage | null;
}

export function emptyAnswer(messageId: string): LiveAnswer {
  return {
    messageId,
    stage: 'retrieving',
    sources: [],
    visual: null,
    awaitingVisual: true,
    text: '',
    citations: [],
    reconnecting: false,
    error: null,
    finished: null,
  };
}

/**
 * Apply one event. Pure, and returns the same object when nothing changed, so React can
 * skip a render for an event that only mattered to the transport.
 */
export function reduceAnswer(state: LiveAnswer, event: AnswerEvent): LiveAnswer {
  switch (event.type) {
    case 'status':
      return { ...state, stage: event.stage, reconnecting: false };

    case 'sources':
      return { ...state, sources: event.sources, reconnecting: false };

    case 'visual':
      return {
        ...state,
        visual: { kind: event.kind, title: event.title, surface: event.surface },
        awaitingVisual: false,
        reconnecting: false,
      };

    case 'visual_skipped':
      return { ...state, visual: null, awaitingVisual: false, reconnecting: false };

    case 'token':
      return { ...state, text: state.text + event.text, reconnecting: false };

    case 'citation': {
      /*
       * Replace rather than append when the number is already known. A resumed stream can
       * legitimately redeliver events the client already applied — `Last-Event-ID` resumes
       * from the last frame *seen*, and a frame in flight when the socket dropped is seen
       * by nobody. Every other case here is idempotent by construction; this one is the
       * exception, and appending would double the footnote list.
       */
      const { type: _type, ...citation } = event;
      const existing = state.citations.findIndex((entry) => entry.n === citation.n);
      const citations =
        existing === -1
          ? [...state.citations, citation]
          : state.citations.map((entry, index) => (index === existing ? citation : entry));
      return { ...state, citations, reconnecting: false };
    }

    case 'done':
      return { ...state, finished: event.message, stage: 'done', reconnecting: false };

    case 'error':
      return {
        ...state,
        error: event.correlation_id
          ? `${event.message} (${event.correlation_id})`
          : event.message,
        stage: 'failed',
        reconnecting: false,
      };
  }
}

/**
 * The stage line's wording. A sentence rather than a state name, and specific once the
 * server has told us how much it read — "Reading 6 passages from 4 documents" is progress,
 * where a spinner is only a promise.
 */
export function stageLabel(state: LiveAnswer): string {
  if (state.reconnecting) return 'Reconnecting…';

  switch (state.stage) {
    case 'retrieving':
      return 'Finding relevant passages';
    case 'reading': {
      if (state.sources.length === 0) return 'Reading the documents';
      const documents = new Set(state.sources.map((source) => source.document_id)).size;
      return (
        `Read ${state.sources.length} ${state.sources.length === 1 ? 'passage' : 'passages'}` +
        ` from ${documents} ${documents === 1 ? 'document' : 'documents'}`
      );
    }
    case 'planning':
      return 'Working out the shape of the answer';
    case 'answering':
      return 'Writing the answer';
    case 'done':
      return state.sources.length > 0 ? sourcesSummary(state.sources) : 'Answered';
    case 'stopped':
      return 'Stopped';
    case 'failed':
      return 'Could not answer';
  }
}

export function sourcesSummary(sources: SourceRef[]): string {
  const documents = new Set(sources.map((source) => source.document_id)).size;
  return (
    `Read ${sources.length} ${sources.length === 1 ? 'passage' : 'passages'}` +
    ` from ${documents} ${documents === 1 ? 'document' : 'documents'}`
  );
}

/** The documents behind an answer, deduplicated, in the order they were first cited. */
export function distinctDocuments(
  sources: SourceRef[],
): { document_id: string; filename: string }[] {
  const seen = new Map<string, string>();
  for (const source of sources) {
    if (!seen.has(source.document_id)) seen.set(source.document_id, source.filename);
  }
  return [...seen].map(([document_id, filename]) => ({ document_id, filename }));
}

/**
 * A persisted message in the same shape as a live one, so one component renders both.
 *
 * History and the stream describe the same thing in two vocabularies — one a database row,
 * the other a fold of events — and the difference is not interesting to the interface. The
 * alternative, a component that branches on where its data came from, gets the two paths
 * out of step the first time either changes.
 *
 * The casts are narrow and deliberate: `sources`, `citations` and `surface` are typed as
 * open records in the generated schema, because FastAPI cannot describe a JSONB column any
 * more precisely than that. The server writes them from the same models the stream events
 * use, so the shapes are identical; `events.py` is the contract for both.
 */
export function answerFromMessage(message: ChatMessage): LiveAnswer {
  const stage: AnswerStage =
    message.status === 'done'
      ? 'done'
      : message.status === 'stopped'
        ? 'stopped'
        : message.status === 'failed'
          ? 'failed'
          : 'answering';

  return {
    messageId: message.id,
    stage,
    sources: (message.sources ?? []) as unknown as SourceRef[],
    visual:
      message.surface && message.surface.length > 0
        ? {
            kind: (message.visual?.kind as VisualKind) ?? 'metric',
            title: (message.visual?.title as string) ?? '',
            surface: message.surface as SurfaceMessage[],
          }
        : null,
    awaitingVisual: false,
    text: message.content,
    citations: (message.citations ?? []) as unknown as Citation[],
    reconnecting: false,
    error: message.error ?? null,
    finished: message,
  };
}
