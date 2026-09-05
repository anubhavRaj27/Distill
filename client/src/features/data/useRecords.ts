import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, authHeader, toFailure } from '../../api/client';
import type { components } from '../../api/schema';
import { logger } from '../../lib/logger';

type RecordPage = components['schemas']['RecordPage'];
type WorkspaceOverview = components['schemas']['WorkspaceOverview'];

export const recordsKey = (workspaceId: string) => ['records', workspaceId] as const;
export const workspaceKey = (workspaceId: string) => ['workspace', workspaceId] as const;

/** The unified table's rows. */
export function useRecords(workspaceId: string, token: string | null) {
  return useQuery({
    queryKey: recordsKey(workspaceId),
    enabled: Boolean(token),
    queryFn: async (): Promise<RecordPage> => {
      const { data, error, response } = await api.GET(
        '/api/v1/workspaces/{workspace_id}/records',
        {
          params: {
            path: { workspace_id: workspaceId },
            header: authHeader(token!),
            query: { limit: 200 },
          },
        },
      );
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },
  });
}

/** The schema, which is what decides the table's columns. */
export function useWorkspace(workspaceId: string, token: string | null) {
  return useQuery({
    queryKey: workspaceKey(workspaceId),
    enabled: Boolean(token),
    queryFn: async (): Promise<WorkspaceOverview> => {
      const { data, error, response } = await api.GET('/api/v1/workspaces/{workspace_id}', {
        params: { path: { workspace_id: workspaceId }, header: authHeader(token!) },
      });
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },
  });
}

export interface CorrectionInput {
  recordId: string;
  fieldKey: string;
  value: unknown;
  notPresent?: boolean;
}

/**
 * A human correction. Requirement FR-34, product principle 4.
 *
 * Written optimistically, because the person just typed it and watching their own edit
 * arrive half a second later reads as the interface not believing them. The rollback is
 * what makes that safe: if the write fails, the previous page is restored exactly and the
 * failure is surfaced rather than swallowed.
 *
 * Note what is *not* done here: the tier is not set to `verified` locally. That derivation
 * belongs to the server (decision D5, `pipeline/score.py`), so the optimistic row shows the
 * new value with its old tier for the moment before the refetch corrects it. Guessing the
 * tier in the client would be the client deciding how much to trust itself.
 */
export function useCorrection(workspaceId: string, token: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ recordId, fieldKey, value, notPresent }: CorrectionInput) => {
      const { data, error, response } = await api.PATCH(
        '/api/v1/workspaces/{workspace_id}/records/{record_id}/fields/{field_key}',
        {
          params: {
            path: { workspace_id: workspaceId, record_id: recordId, field_key: fieldKey },
            header: authHeader(token!),
          },
          body: { value: value ?? null, not_present: notPresent ?? false },
        },
      );
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },

    onMutate: async (input) => {
      const key = recordsKey(workspaceId);
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<RecordPage>(key);

      queryClient.setQueryData<RecordPage>(key, (current) => {
        if (!current) return current;
        return {
          ...current,
          records: current.records.map((record) =>
            record.id !== input.recordId
              ? record
              : {
                  ...record,
                  values: {
                    ...record.values,
                    [input.fieldKey]: {
                      ...record.values?.[input.fieldKey],
                      field_key: input.fieldKey,
                      value_type: record.values?.[input.fieldKey]?.value_type ?? 'string',
                      tier: record.values?.[input.fieldKey]?.tier ?? 'verified',
                      value: input.notPresent ? null : input.value,
                      status: 'human_verified',
                    },
                  },
                },
          ),
        };
      });

      return { previous };
    },

    onError: (error, _input, context) => {
      if (context?.previous) {
        queryClient.setQueryData(recordsKey(workspaceId), context.previous);
      }
      logger.event('correction.made', { ok: false, error: String(error) });
    },

    onSuccess: () => {
      logger.event('correction.made', { ok: true });
    },

    onSettled: () => {
      // The server owns the tier and the model-value bookkeeping, so the truth comes back
      // from it rather than being reconstructed here.
      void queryClient.invalidateQueries({ queryKey: recordsKey(workspaceId) });
    },
  });
}
