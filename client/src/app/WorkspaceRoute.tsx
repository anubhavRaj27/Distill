import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useLocation, useParams } from 'react-router';
import styled from 'styled-components';

import { api, authHeader, toFailure } from '../api/client';
import { AppHeader } from './AppHeader';
import { consumeTokenFromFragment, recallToken } from '../lib/workspace-token';
import { logger } from '../lib/logger';

/**
 * A placeholder for screens 2 and 3, Chat and Data.
 *
 * It carries the real application header — so the workspace chip, the three-screen switch,
 * and "Add documents" are live rather than dead code — and then renders the cold-start
 * payload as plain text and nothing more. The conversation, the table, the viewer, and the
 * dashboard are the next slice of work and are deliberately not sketched here: a half-drawn
 * shell is harder to replace than an empty one.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

const Body = styled.div`
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.xl};
  padding: ${({ theme }) => theme.space.xxl} ${({ theme }) => theme.space.page};
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
  const { pathname } = useLocation();

  // Chat is the product's main screen, so a bare `/w/{id}` is Chat rather than a fourth,
  // nameless place (requirements section 3.2).
  const active = pathname.endsWith('/data') ? ('data' as const) : ('chat' as const);

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
        <AppHeader />
        <Body>
          <Note>
            This workspace needs its access token, and this browser does not have it. Open
            the link you were given in full, including everything after the <code>#</code>.
          </Note>
        </Body>
      </Page>
    );
  }

  const documents = overview.data?.documents ?? [];

  return (
    <Page>
      <AppHeader
        active={active}
        workspace={{
          id: workspaceId,
          // The server allows an unlabelled workspace; the header still needs something to
          // show, and "Untitled workspace" is honest where a blank line would look broken.
          label: overview.data?.label ?? 'Untitled workspace',
          documentCount: documents.length,
        }}
        onAddDocuments={() => {
          // Requirement FR-06. The control is real so the header is not a mock-up; the
          // picker it opens arrives with the workspace shell.
          logger.event('upload.start', { from: 'workspace-header' });
        }}
      />

      <Body>
        <Note>
          Workspace ready. Chat and Data are the next screens to be built. What follows is
          the cold-start payload, unstyled.
        </Note>

        {overview.isPending && <Note>Loading…</Note>}
        {overview.isError && <Note role="alert">{overview.error.message}</Note>}

        {overview.data && (
          <Docs>
            {documents.map((document) => (
              <li key={document.id}>
                {document.filename} — {document.status}
                {document.failure_reason ? ` (${document.failure_reason})` : ''}
              </li>
            ))}
          </Docs>
        )}
      </Body>
    </Page>
  );
}
