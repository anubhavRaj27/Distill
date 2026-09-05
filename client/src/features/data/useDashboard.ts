import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

/**
 * The dashboard's data.
 *
 * `GET /workspaces/{id}/dashboard` and `POST /dashboard/generate` are planned
 * (implementation.md section 5, marked "new") but **not built** — `server/app/insights/`
 * has `queryspec.py`, `evaluate.py` and `stats.py`, and no `dashboard.py` or router. So
 * this hook talks to routes that currently answer 404, and turns that into the `absent`
 * state rather than an error: "the agent has not generated panels yet" is exactly what a
 * missing dashboard means, and it is a state the screen has to render properly anyway.
 *
 * When the routes land, this hook keeps its shape and the screen does not change.
 */

export interface DashboardPanel {
  id: string;
  title: string;
  rationale?: string;
  /** The A2UI surface messages, once the catalog exists. Untouched here. */
  surface?: unknown;
}

export type DashboardState =
  | { status: 'absent'; stale: false; newDocuments: 0 }
  | { status: 'generating'; stale: boolean; newDocuments: number }
  | { status: 'ready'; stale: boolean; newDocuments: number; panels: DashboardPanel[] }
  | { status: 'failed'; stale: boolean; newDocuments: number; error: string };

interface DashboardResponse {
  status?: 'pending' | 'ready' | 'failed';
  stale?: boolean;
  new_documents?: number;
  panels?: DashboardPanel[];
  error?: string;
}

const dashboardKey = (workspaceId: string) => ['dashboard', workspaceId] as const;

const ABSENT: DashboardState = { status: 'absent', stale: false, newDocuments: 0 };

function toState(body: DashboardResponse | null): DashboardState {
  if (!body || !body.status) return ABSENT;

  const stale = Boolean(body.stale);
  const newDocuments = body.new_documents ?? 0;

  switch (body.status) {
    case 'pending':
      return { status: 'generating', stale, newDocuments };
    case 'failed':
      return {
        status: 'failed',
        stale,
        newDocuments,
        error:
          body.error ??
          "Couldn't generate the dashboard. The table is unaffected — you can try again.",
      };
    case 'ready':
      return { status: 'ready', stale, newDocuments, panels: body.panels ?? [] };
  }
}

export function useDashboard(workspaceId: string, token: string | null) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: dashboardKey(workspaceId),
    enabled: Boolean(token),
    // A 404 is a legitimate answer here, so failures are not retried into a spinner.
    retry: false,
    queryFn: async (): Promise<DashboardState> => {
      const response = await fetch(`/api/v1/workspaces/${workspaceId}/dashboard`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      // Not built yet, or never generated. Both mean the same thing to a person.
      if (response.status === 404) return ABSENT;

      if (!response.ok) {
        return {
          status: 'failed',
          stale: false,
          newDocuments: 0,
          error: `The dashboard could not be loaded (${response.status}). The table is unaffected.`,
        };
      }

      return toState((await response.json()) as DashboardResponse);
    },
  });

  const regenerate = useMutation({
    mutationFn: async () => {
      const response = await fetch(
        `/api/v1/workspaces/${workspaceId}/dashboard/generate`,
        { method: 'POST', headers: { Authorization: `Bearer ${token}` } },
      );
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? 'Dashboard generation is not available on this server yet.'
            : `Dashboard generation failed (${response.status}).`,
        );
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: dashboardKey(workspaceId) });
    },
  });

  const state: DashboardState = regenerate.isError
    ? {
        status: 'failed',
        stale: false,
        newDocuments: 0,
        error: regenerate.error.message,
      }
    : regenerate.isPending
      ? { status: 'generating', stale: false, newDocuments: 0 }
      : (query.data ?? ABSENT);

  return { state, regenerate: () => regenerate.mutate() };
}
