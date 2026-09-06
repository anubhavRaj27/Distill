import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { api, authHeader, toFailure, type ApiFailure } from '../../api/client';
import type { RejectedFile } from '../../lib/files';
import { rememberWorkspace } from '../../lib/workspace-token';
import { logger } from '../../lib/logger';
import { usePendingUploads } from './pendingUploads';

/**
 * Starting a workspace from screen 1. Requirements FR-01, FR-02, FR-05.
 *
 * Both ways in mint an anonymous workspace first, and then diverge, because only one of
 * them moves bytes out of this browser:
 *
 * - **Files.** The selection is staged and the person is sent to `/w/{id}/upload`, which
 *   owns the transfer and shows a bar per file. Uploading here instead would mean a screen
 *   that cannot report progress holding a screen that exists to report it.
 * - **Samples.** The server loads them from its own disk. There is nothing
 *   for a progress bar to measure, and this used to go straight to Chat for that reason —
 *   which meant the sample path, the one a reviewer takes, skipped the screen that narrates
 *   the reading of the documents entirely. It now lands on the same upload screen, where
 *   there is a great deal to watch even with no bytes moving: parsing, extraction and
 *   indexing, per document. See decision D36.
 */

export type StartIntent =
  | { kind: 'files'; files: File[]; rejected: RejectedFile[] }
  | { kind: 'samples' };

interface StartedWorkspace {
  workspaceId: string;
  token: string;
  intent: StartIntent['kind'];
}

async function createWorkspace(): Promise<{ workspaceId: string; token: string }> {
  const { data, error, response } = await api.POST('/api/v1/workspaces', {
    body: { label: null },
  });

  if (error || !data) throw toFailure(error, response?.status);

  // The token is returned exactly once and only its hash is stored server-side, so it is
  // written to storage before anything else can fail (decision D7).
  rememberWorkspace(data.id, data.token);
  return { workspaceId: data.id, token: data.token };
}

export function useStartWorkspace() {
  const navigate = useNavigate();
  const stage = usePendingUploads((state) => state.stage);

  return useMutation<StartedWorkspace, ApiFailure, StartIntent>({
    mutationFn: async (intent) => {
      const { workspaceId, token } = await createWorkspace();

      if (intent.kind === 'files') {
        // Handed to the upload screen rather than sent from here, refusals included so
        // FR-03's message survives the navigation.
        stage(workspaceId, intent.files, intent.rejected);
        return { workspaceId, token, intent: 'files' };
      }

      logger.event('samples.start', {});
      /*
       * Nothing to stage, and staged anyway: an entry for this workspace is how the upload
       * screen knows a person arrived through the front door rather than by clicking the
       * Upload tab, which is what decides whether the reading is worth confirming and
       * whether Continue waits for it (decisions D36). The screen clears the entry on
       * mount, so it says "this arrival", not "this workspace".
       */
      stage(workspaceId, [], []);
      const { error, response } = await api.POST(
        '/api/v1/workspaces/{workspace_id}/documents/seed',
        { params: { path: { workspace_id: workspaceId }, header: authHeader(token) } },
      );
      if (error) throw toFailure(error, response?.status);

      return { workspaceId, token, intent: 'samples' };
    },
    onSuccess: ({ workspaceId }) => {
      // Both ways in land on the same screen. The token is already in storage, so in-app
      // navigation does not carry it; the fragment form exists for links a person shares
      // (decision D21).
      void navigate(`/w/${workspaceId}/upload`);
    },
    onError: (failure) => {
      logger.event('workspace.start.failed', {
        message: failure.message,
        correlation_id: failure.correlationId,
      });
    },
  });
}
