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
 * - **Samples.** The server loads them from its own disk (decision D15). There is nothing
 *   for a progress bar to measure, so this goes straight to Chat, where the processing
 *   strip picks the story up.
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
  // written to storage before anything else can fail (decision D8).
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
      const { error, response } = await api.POST(
        '/api/v1/workspaces/{workspace_id}/documents/seed',
        { params: { path: { workspace_id: workspaceId }, header: authHeader(token) } },
      );
      if (error) throw toFailure(error, response?.status);

      return { workspaceId, token, intent: 'samples' };
    },
    onSuccess: ({ workspaceId, intent }) => {
      // The token is already in storage, so in-app navigation does not carry it. The
      // fragment form exists for links a person shares (decision D31).
      void navigate(intent === 'files' ? `/w/${workspaceId}/upload` : `/w/${workspaceId}/chat`);
    },
    onError: (failure) => {
      logger.event('workspace.start.failed', {
        message: failure.message,
        correlation_id: failure.correlationId,
      });
    },
  });
}
