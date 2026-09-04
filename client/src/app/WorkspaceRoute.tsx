import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router';
import styled from 'styled-components';

import { api, authHeader, toFailure } from '../api/client';
import { Wordmark } from '../ui/Wordmark';
import { consumeTokenFromFragment, recallToken } from '../lib/workspace-token';

/**
 * A placeholder for screen 2, the workspace shell.
 *
 * It exists so the first-run screen has somewhere real to land: it proves the workspace
 * was created, the token round-trips, and the documents reached the server. It renders the
 * cold-start payload as plain text and nothing more. The table, schema panel, processing
 * list, review queue, and command bar are the next slice of work, and they are not
 * sketched here — a half-drawn shell would be harder to replace than an empty one.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  padding: ${({ theme }) => theme.space.xxl} ${({ theme }) => theme.space.page};
  gap: ${({ theme }) => theme.space.xl};
`;

const Note = styled.p`
  font-size: 14px;
  color: ${({ theme }) => theme.color.inkMuted};
  max-width: ${({ theme }) => theme.measure.narrow};
`;

const Docs = styled.ul`
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.sm};
  font-family: ${({ theme }) => theme.font.mono};
  font-size: 13px;
`;

export function WorkspaceRoute() {
  const { workspaceId = '' } = useParams();

  // Runs once on arrival: a shared link carries the token in its fragment, which is moved
  // into storage and stripped from the address bar before anything renders it.
  const [token] = useState(
    () => consumeTokenFromFragment(workspaceId) ?? recallToken(workspaceId),
  );

  useEffect(() => {
    document.title = 'Distill · workspace';
  }, []);

  const overview = useQuery({
    queryKey: ['workspace', workspaceId],
    enabled: Boolean(token),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/workspaces/{workspace_id}', {
        params: { path: { workspace_id: workspaceId }, header: authHeader(token!) },
      });
      if (error || !data) throw toFailure(error, response?.status);
      return data;
    },
  });

  if (!token) {
    return (
      <Page>
        <Wordmark />
        <Note>
          This workspace needs its access token, and this browser does not have it. Open the
          link you were given in full, including everything after the <code>#</code>.
        </Note>
      </Page>
    );
  }

  return (
    <Page>
      <Wordmark />
      <Note>
        Workspace ready. The shell — table, schema panel, processing list, review queue — is
        the next screen to be built. What follows is the cold-start payload, unstyled.
      </Note>

      {overview.isPending && <Note>Loading…</Note>}
      {overview.isError && <Note role="alert">{overview.error.message}</Note>}

      {overview.data && (
        <Docs>
          {(overview.data.documents ?? []).map((document) => (
            <li key={document.id}>
              {document.filename} — {document.status}
              {document.failure_reason ? ` (${document.failure_reason})` : ''}
            </li>
          ))}
        </Docs>
      )}
    </Page>
  );
}
