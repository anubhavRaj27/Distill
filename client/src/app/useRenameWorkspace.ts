import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, authHeader, toFailure } from '../api/client';
import type { components } from '../api/schema';

type WorkspaceOverview = components['schemas']['WorkspaceOverview'];

/**
 * Rename a workspace. Decision D77.
 *
 * The name is generated once from the first batch of documents and never regenerated, so
 * this is the only thing that ever changes it after that — which is why the new name is
 * written into the cache from the response rather than optimistically: there is no race to
 * win, and the server trims and truncates, so the value it returns is the true one.
 */
export function useRenameWorkspace(workspaceId: string, token: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (label: string) => {
      const { data, error, response } = await api.PATCH('/api/v1/workspaces/{workspace_id}', {
        params: { path: { workspace_id: workspaceId }, header: authHeader(token!) },
        body: { label },
      });
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },

    onSuccess: (overview) => {
      queryClient.setQueryData<WorkspaceOverview>(['workspace', workspaceId], overview);
    },
  });
}
