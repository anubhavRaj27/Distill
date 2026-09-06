import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, authHeader, toFailure } from '../../api/client';
import type { components } from '../../api/schema';
import { logger } from '../../lib/logger';

type WorkspaceOverview = components['schemas']['WorkspaceOverview'];

/**
 * Remove a document and everything derived from it. Requirement FR-07, decision D44.
 *
 * Not optimistic, unlike a cell correction. A correction is the person's own typing coming
 * back to them and showing it immediately is honest; a deletion cascades server-side through
 * the extracted row, the passages and every citation pointing at them, and a row that
 * vanishes and then reappears because the request failed is worse than a row that takes a
 * moment to go.
 *
 * Both the overview and the records page are invalidated, because the document was in both.
 * The dashboard is left alone deliberately: the server marks it stale, and the Data screen
 * already knows how to say so.
 */
export function useDeleteDocument(workspaceId: string, token: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (documentId: string) => {
      const { error, response } = await api.DELETE(
        '/api/v1/workspaces/{workspace_id}/documents/{document_id}',
        {
          params: {
            path: { workspace_id: workspaceId, document_id: documentId },
            header: authHeader(token!),
          },
        },
      );
      // A 204 carries no body, so `data` is empty on success and only `error` decides.
      if (error) throw toFailure(error, response?.status);
      return documentId;
    },

    onSuccess: (documentId) => {
      logger.event('document.deleted', { documentId });

      /*
       * The row is dropped from the cached overview by hand before anything is refetched.
       * Invalidating alone was not enough in practice: the refetch returned the shorter
       * list and the deleted row stayed on screen until a reload, which reads as the
       * deletion having failed. Writing the known outcome into the cache is also simply
       * more honest than asking the server to tell us what we just told it.
       */
      queryClient.setQueryData<WorkspaceOverview>(['workspace', workspaceId], (current) =>
        current
          ? {
              ...current,
              documents: (current.documents ?? []).filter(
                (document) => document.id !== documentId,
              ),
            }
          : current,
      );

      // Then the round trip, for everything derived from it: the record count, the schema
      // if that document held the only instance of a field, the dashboard's staleness.
      void queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] });
      void queryClient.invalidateQueries({ queryKey: ['records', workspaceId] });
    },

    onError: (error) => {
      logger.event('document.delete_failed', { message: String(error) });
    },
  });
}
