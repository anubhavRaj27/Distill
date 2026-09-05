import { useQuery } from '@tanstack/react-query';

import { api, authHeader, toFailure } from '../../api/client';

/**
 * Three questions worth asking, generated from the schema that was actually inferred and
 * the values actually extracted (requirements section 3.2, item 1).
 *
 * Generated rather than hard-coded because the corpus is not known in advance: "which
 * vendor did we spend most with" is a good opener for invoices and meaningless for research
 * papers, and section 1.4 promises both the same experience. The server returns an empty
 * list until a schema exists, which is the signal to show nothing at all rather than
 * placeholder questions that would fail if asked.
 *
 * `enabled` gates on a document having finished, so this does not fire once per second
 * against a workspace that is still parsing.
 */
export function useSuggestions(
  workspaceId: string,
  token: string | null,
  ready: boolean,
) {
  return useQuery({
    queryKey: ['chat', workspaceId, 'suggestions'],
    enabled: Boolean(token) && ready,
    // Regenerating these costs a model call, and they do not change while a person reads
    // them. They are refreshed by the schema changing, not by time passing.
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        '/api/v1/workspaces/{workspace_id}/chat/suggestions',
        {
          params: { path: { workspace_id: workspaceId }, header: authHeader(token!) },
        },
      );
      if (error || !data) throw toFailure(error, response?.status);
      return data.questions;
    },
  });
}
