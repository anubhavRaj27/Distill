/**
 * A Server-Sent Events client built on `fetch`, not on `EventSource`.
 *
 * `EventSource` would be the obvious choice and cannot be used, for one blunt reason: it
 * sends no request headers. Every route in this API authorises with
 * `Authorization: Bearer <workspace token>` (decision D7), and there is no query-parameter
 * fallback — deliberately, since a token in a URL ends up in logs, history and referrers.
 * So the stream is read as a `fetch` body instead.
 *
 * Two things follow, and both are requirements rather than consolation prizes:
 *
 * - **Reconnection is ours to implement.** `EventSource` retries and replays
 *   `Last-Event-ID` for free; here that is the loop below. Requirement FR-29 asks for
 *   exactly this, and both of this product's streams number their events with a resumable
 *   sequence for it (`routers/events.py`, `routers/chat.py`).
 * - **Cancellation is an `AbortSignal`,** which composes with React effect cleanup and with
 *   `AbortController` chaining, where `EventSource.close()` composes with nothing.
 *
 * The parser implements the wire format from the HTML specification: `field: value` lines,
 * a blank line to dispatch, `data` accumulating across lines, and a leading colon marking a
 * comment. Comments matter here — `sse-starlette` sends its keep-alive as one — and are
 * dropped rather than dispatched.
 */

export interface SseMessage {
  /** The `id:` field. Sent back as `Last-Event-ID` when the stream is resumed. */
  id?: string;
  /** The `event:` field, or `message` when the server did not name one. */
  event: string;
  /** The accumulated `data:` lines, newline-joined. */
  data: string;
}

export interface ConsumeOptions {
  url: string;
  headers?: Record<string, string>;
  signal: AbortSignal;
  /** Resume point for the first attempt, for a stream picked up across a remount. */
  lastEventId?: string;
  onMessage: (message: SseMessage) => void;
  /** Called before each retry, so an interface can say it is reconnecting. */
  onReconnect?: (attempt: number) => void;
  /** Attempts after the first. Exceeding it throws the last error to the caller. */
  maxRetries?: number;
}

const DEFAULT_MAX_RETRIES = 5;

/** Exponential with a ceiling: 0.5s, 1s, 2s, 4s, 8s, then 8s forever. */
function backoffMs(attempt: number): number {
  return Math.min(500 * 2 ** (attempt - 1), 8000);
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/**
 * Split a buffer into complete events.
 *
 * Returns the events it could parse and whatever partial text is left over, because a
 * network chunk boundary falls wherever it likes — routinely mid-line, and for a token
 * stream, routinely mid-word.
 */
export function parseChunk(buffer: string): { messages: SseMessage[]; rest: string } {
  const messages: SseMessage[] = [];

  // The spec treats CRLF, CR and LF alike. Normalising once here means the field parser
  // below only ever has to think about one of them.
  const normalised = buffer.replace(/\r\n|\r/g, '\n');

  let start = 0;
  let separator = normalised.indexOf('\n\n', start);
  while (separator !== -1) {
    const block = normalised.slice(start, separator);
    const message = parseBlock(block);
    if (message) messages.push(message);
    start = separator + 2;
    separator = normalised.indexOf('\n\n', start);
  }

  return { messages, rest: normalised.slice(start) };
}

function parseBlock(block: string): SseMessage | null {
  let id: string | undefined;
  let event: string | undefined;
  const data: string[] = [];

  for (const line of block.split('\n')) {
    // A line starting with a colon is a comment. `sse-starlette`'s heartbeat is one, so
    // this branch runs every fifteen seconds on an idle stream.
    if (line === '' || line.startsWith(':')) continue;

    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    // Exactly one leading space after the colon is part of the framing, not the value.
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    switch (field) {
      case 'id':
        id = value;
        break;
      case 'event':
        event = value;
        break;
      case 'data':
        data.push(value);
        break;
      // `retry` is ignored: the backoff here is ours, and no route sets it.
      default:
        break;
    }
  }

  // A block of nothing but comments dispatches nothing.
  if (data.length === 0 && event === undefined) return null;

  return { id, event: event ?? 'message', data: data.join('\n') };
}

/**
 * Read a stream until it ends, the signal aborts, or reconnection gives up.
 *
 * Resolves when the server closes the stream normally — for these routes that means the
 * answer finished. Rejects on abort (with the signal's reason) or when the retries are
 * exhausted, so a caller can tell "finished" from "gave up" without inspecting state.
 */
export async function consumeSse(options: ConsumeOptions): Promise<void> {
  const { url, headers, signal, onMessage, onReconnect } = options;
  const maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;

  let lastEventId = options.lastEventId;
  let attempt = 0;

  for (;;) {
    signal.throwIfAborted();

    try {
      const response = await fetch(url, {
        method: 'GET',
        signal,
        headers: {
          accept: 'text/event-stream',
          // Sent on the first attempt too: a stream may be resumed across a remount, not
          // only across a dropped socket.
          ...(lastEventId ? { 'Last-Event-ID': lastEventId } : {}),
          ...headers,
        },
      });

      if (!response.ok) {
        /*
         * A 4xx is the server's considered answer, not a blip. Retrying an expired token
         * or a message that does not exist just repeats the same refusal on a timer, so
         * these throw straight to the caller.
         */
        if (response.status >= 400 && response.status < 500) {
          throw new SseError(
            `The server refused the stream (${response.status}).`,
            response.status,
          );
        }
        throw new Error(`The stream failed to open (${response.status}).`);
      }

      if (!response.body) throw new Error('The stream arrived with no body to read.');

      // A byte that lands mid-character survives across chunks with `stream: true`; without
      // it a multi-byte character split across a boundary decodes as a replacement glyph.
      const decoder = new TextDecoder();
      const reader = response.body.getReader();
      let buffer = '';

      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const { messages, rest } = parseChunk(buffer);
          buffer = rest;

          for (const message of messages) {
            if (message.id) lastEventId = message.id;
            onMessage(message);
          }
        }
      } finally {
        // The response body is not garbage on its own while a reader holds it open.
        reader.releaseLock();
      }

      // The server closed the stream. For both of this app's routes that is the end.
      return;
    } catch (error) {
      if (isAbort(error) || signal.aborted) throw signal.reason ?? error;
      if (error instanceof SseError) throw error;

      attempt += 1;
      if (attempt > maxRetries) throw error;

      onReconnect?.(attempt);
      await delay(backoffMs(attempt), signal);
      // Round again, with `lastEventId` carrying the resume point.
    }
  }
}

/** A refusal the server meant, as opposed to a connection that dropped. */
export class SseError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'SseError';
    this.status = status;
  }
}
