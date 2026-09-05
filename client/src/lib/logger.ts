/**
 * Structured client events.
 *
 * The observability requirement asks for a named event vocabulary rather than scattered
 * `console.log` calls: `upload.start`, `extract.done`, `correction.made`, `query.run`,
 * `a2ui.fallback`. In development they go to the console; in production they will batch to
 * `POST /api/v1/client-events` (implementation.md section 10), which is why callers never
 * touch `console` directly.
 */

type EventName =
  | 'upload.start'
  | 'samples.start'
  | 'workspace.start.failed'
  | 'files.rejected'
  | 'correction.made'
  | 'query.run'
  | 'a2ui.fallback'
  /*
   * The answer stream. Reconnects and reattachments are the events worth having when
   * someone reports "the answer stopped halfway": each says which message, so a client
   * report lines up with the server's own `chat.stream_opened` / `chat.stream_closed`.
   */
  | 'chat.asked'
  | 'chat.stream_reconnect'
  | 'chat.stream_reattach'
  | 'chat.stream_failed'
  /*
   * The document library on the Upload screen (decision D71). A deletion cascades through
   * the extracted row, the passages and the citations, so "was it asked for, and did it
   * work" is worth having when someone reports a document that should still be there.
   */
  | 'document.deleted'
  | 'document.delete_failed';

type Payload = Record<string, unknown>;

export const logger = {
  event(name: EventName, payload: Payload = {}): void {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.info(`[distill] ${name}`, payload);
    }
    // Production transport is deliberately not built yet: it needs the batching endpoint,
    // which lands with the workspace shell. One call site, one change.
  },
};
