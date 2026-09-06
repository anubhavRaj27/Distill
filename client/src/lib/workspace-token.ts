/**
 * Workspace identity. Requirement FR-01, decision D7 (no accounts), decision D21 (the
 * token travels in the URL fragment).
 *
 * The bearer token is issued once at workspace creation and is never recoverable — the
 * server stores only its hash. Losing it means losing the workspace, so it is written to
 * `localStorage` the moment it is minted.
 *
 * A shareable link carries the token in the URL **fragment** (`#t=…`), never the query
 * string. A fragment is not transmitted to the server, so the credential stays out of
 * access logs, `Referer` headers, and anything sitting in front of the application. On
 * arrival the fragment is consumed into `localStorage` and stripped from the address bar,
 * so it does not linger in browser history either.
 */

const TOKEN_KEY = (workspaceId: string) => `distill.token.${workspaceId}`;
const LAST_WORKSPACE_KEY = 'distill.lastWorkspace';

/** Reading storage can throw outright in a locked-down browser, so every access is guarded. */
function safeRead(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeWrite(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A workspace held only in memory still works for this tab, which is a better outcome
    // than refusing to start because storage is unavailable.
  }
}

export function rememberWorkspace(workspaceId: string, token: string): void {
  safeWrite(TOKEN_KEY(workspaceId), token);
  safeWrite(LAST_WORKSPACE_KEY, workspaceId);
}

export function recallToken(workspaceId: string): string | null {
  return safeRead(TOKEN_KEY(workspaceId));
}

export function recallLastWorkspaceId(): string | null {
  return safeRead(LAST_WORKSPACE_KEY);
}

/** The link a person copies to hand this workspace to a colleague. */
export function shareableUrl(workspaceId: string, token: string): string {
  return `${window.location.origin}/w/${workspaceId}#t=${encodeURIComponent(token)}`;
}

/**
 * Take the token out of the address bar and into storage.
 *
 * Called once when a workspace route mounts. Returns the token if the fragment carried
 * one, so the caller can use it immediately rather than reading storage back.
 */
export function consumeTokenFromFragment(workspaceId: string): string | null {
  const fragment = window.location.hash.startsWith('#')
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!fragment) return null;

  const token = new URLSearchParams(fragment).get('t');
  if (!token) return null;

  rememberWorkspace(workspaceId, token);
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
  return token;
}
