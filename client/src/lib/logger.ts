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
  | 'a2ui.fallback';

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
