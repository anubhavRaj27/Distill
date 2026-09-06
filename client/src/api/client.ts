import createClient from 'openapi-fetch';

import type { paths } from './schema';

/**
 * The typed API client.
 *
 * Request and response shapes are generated from the server's own OpenAPI document
 * (`npm run api:types`), so there are no hand-written request types to drift out of step
 * with the backend. A route that changes shape becomes a TypeScript error here rather than
 * a runtime surprise in the browser.
 */

/**
 * Empty in development, where Vite proxies `/api` to the server (see `vite.config.ts`), and
 * empty in production, where FastAPI serves the built assets itself so there is no
 * cross-origin surface at all (implementation.md section 10). The variable exists for the
 * one case in between: pointing a local interface at a deployed API.
 */
const BASE_URL = import.meta.env.VITE_API_URL ?? '';

export const api = createClient<paths>({
  baseUrl: BASE_URL,
  /*
   * Resolved per call rather than captured once. `createClient` otherwise binds whatever
   * `globalThis.fetch` was at module-load time, which makes the transport impossible to
   * substitute afterwards — in tests, and equally for anything that would wrap fetch at
   * runtime. One indirection buys that back.
   */
  fetch: (...args) => globalThis.fetch(...args),
});

/**
 * Workspace credentials travel as a bearer token on every request (decision D7).
 *
 * The server declares `authorization` as an explicit header parameter, so it is passed
 * through `params.header` rather than being injected by middleware. That keeps it visible
 * at each call site, which is the right default for a credential.
 */
export function authHeader(token: string): { authorization: string } {
  return { authorization: `Bearer ${token}` };
}

/**
 * Turn a failed response into something a person can act on.
 *
 * The server's error envelope carries a `correlation_id`; surfacing it is what makes a bug
 * report traceable to a single request in the logs (the observability requirement). When
 * the shape is not recognised — a proxy error page, an offline browser — the caller still
 * gets a sentence rather than `[object Object]`.
 */
export interface ApiFailure {
  message: string;
  correlationId?: string;
  status?: number;
}

export function toFailure(error: unknown, status?: number): ApiFailure {
  if (error && typeof error === 'object') {
    const body = error as Record<string, unknown>;
    const detail = body.detail ?? body.message;
    const correlationId = body.correlation_id;

    if (typeof detail === 'string') {
      return {
        message: detail,
        correlationId: typeof correlationId === 'string' ? correlationId : undefined,
        status,
      };
    }
  }

  if (status === undefined) {
    return {
      message:
        'Could not reach Distill. Check that the server is running, then try again.',
    };
  }

  return { message: `The server responded with an unexpected error (${status}).`, status };
}
