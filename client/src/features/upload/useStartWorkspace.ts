import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { api, authHeader, toFailure, type ApiFailure } from '../../api/client';
import { rememberWorkspace } from '../../lib/workspace-token';
import { logger } from '../../lib/logger';

/**
 * Starting a workspace from the first-run screen. Requirements FR-01, FR-02, FR-05.
 *
 * Both entry points on this screen — dropping your own files, or asking for the sample
 * set — are the same two steps: mint an anonymous workspace, then give it something to
 * read. They are modelled as one mutation with two shapes rather than two hooks, because
 * the failure handling, the token persistence, and the navigation are identical and
 * should not be written twice.
 *
 * The workspace is created first and navigated to immediately. Processing is asynchronous
 * on the server and streams over Server-Sent Events, so the person watches the pipeline
 * run rather than watching a spinner on this screen.
 */

export type StartIntent = { kind: 'files'; files: File[] } | { kind: 'samples' };

interface StartedWorkspace {
  workspaceId: string;
  token: string;
}

async function createWorkspace(): Promise<StartedWorkspace> {
  const { data, error, response } = await api.POST('/api/v1/workspaces', {
    body: { label: null },
  });

  if (error || !data) throw toFailure(error, response?.status);

  // The token is returned exactly once and only its hash is stored server-side, so it is
  // written to storage before anything else can fail (decision D8).
  rememberWorkspace(data.id, data.token);
  return { workspaceId: data.id, token: data.token };
}

async function uploadFiles(
  { workspaceId, token }: StartedWorkspace,
  files: File[],
): Promise<void> {
  const form = new FormData();
  for (const file of files) form.append('files', file);

  const { error, response } = await api.POST(
    '/api/v1/workspaces/{workspace_id}/documents',
    {
      params: { path: { workspace_id: workspaceId }, header: authHeader(token) },
      // openapi-fetch serialises a plain object as JSON; a multipart upload has to pass
      // the FormData through untouched, which is what `bodySerializer` is for.
      body: form as never,
      bodySerializer: (body: unknown) => body as FormData,
    },
  );

  if (error) throw toFailure(error, response?.status);
}

async function seedSamples({ workspaceId, token }: StartedWorkspace): Promise<void> {
  const { error, response } = await api.POST(
    '/api/v1/workspaces/{workspace_id}/documents/seed',
    { params: { path: { workspace_id: workspaceId }, header: authHeader(token) } },
  );

  if (error) throw toFailure(error, response?.status);
}

export function useStartWorkspace() {
  const navigate = useNavigate();

  return useMutation<StartedWorkspace, ApiFailure, StartIntent>({
    mutationFn: async (intent) => {
      const started = await createWorkspace();

      if (intent.kind === 'files') {
        logger.event('upload.start', { files: intent.files.length });
        await uploadFiles(started, intent.files);
      } else {
        logger.event('samples.start', {});
        await seedSamples(started);
      }

      return started;
    },
    onSuccess: ({ workspaceId }) => {
      // The token is already in storage, so the in-app navigation does not need to carry
      // it. The fragment form exists for links a person shares (decision D31).
      void navigate(`/w/${workspaceId}`);
    },
    onError: (failure) => {
      logger.event('workspace.start.failed', {
        message: failure.message,
        correlation_id: failure.correlationId,
      });
    },
  });
}
