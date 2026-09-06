import { useCallback, useState } from 'react';
import { useParams } from 'react-router';
import styled from 'styled-components';

import { AppHeader } from '../../app/AppHeader';
import { useRenameWorkspace } from '../../app/useRenameWorkspace';
import { consumeTokenFromFragment, recallToken } from '../../lib/workspace-token';
import { Dashboard } from './Dashboard';
import { DocumentSummary } from './DocumentSummary';
import { RecordsTable } from './RecordsTable';
import { TierLegend } from './cells/TierMark';
import { useCorrection, useDashboard, useRecords, useWorkspace } from './hooks';

/**
 * Screen 3 of three: Data. Route `/w/{id}/data`.
 *
 * Two things side by side, and the split is not decorative. On the left, everything that
 * came out of the documents, cell by cell, with its provenance and its confidence — the
 * evidence. On the right, what the agent made of it — the interpretation. Keeping them
 * apart is the whole trust argument of the screen: a person can always walk from a number
 * in a panel back to the row, and from the row to the highlighted region of the page.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

const Main = styled.main`
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0 ${({ theme }) => theme.space.xl};
`;

const TitleBar = styled.div`
  display: flex;
  align-items: center;
  height: 40px;
  flex-shrink: 0;
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  h1 {
    font-family: ${({ theme }) => theme.font.display};
    font-weight: 400;
    font-size: 17px;
    color: ${({ theme }) => theme.color.ink};
  }
`;

const Columns = styled.div`
  flex: 1;
  min-height: 0;
  display: grid;
  /*
   * Fractions, not percentages, and the difference was the whole bug.
   *
   * 62% 38% resolves against the container's content box and knows nothing about the
   * gap, so the tracks summed to 100% of the width PLUS 24px. The dashboard column hung
   * exactly one gap over the right edge of the page — past the padding, flush against the
   * window — while the table column kept its share. fr is the unit that divides what is
   * left after the gap, which is what was meant. minmax(0, ...) on both tracks stops a wide
   * table or a long panel title from pushing its track past its share.
   */
  grid-template-columns: minmax(0, 62fr) minmax(0, 38fr);
  gap: ${({ theme }) => theme.space.xl};
  padding: ${({ theme }) => theme.space.lg} 0 ${({ theme }) => theme.space.xl};

  /* Below this the two columns stop being readable side by side and stack instead. */
  @media (max-width: 1100px) {
    grid-template-columns: minmax(0, 1fr);
  }
`;

const Left = styled.section`
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
`;

const SectionHead = styled.div`
  h2 {
    font-family: ${({ theme }) => theme.font.display};
    font-weight: 400;
    font-size: 15px;
    color: ${({ theme }) => theme.color.ink};
  }
  p {
    font-size: 11px;
    line-height: 1.45;
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

const EditHint = styled.p`
  font-size: 10px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Message = styled.p`
  padding: ${({ theme }) => theme.space.xl};
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

export function DataScreen() {
  const { workspaceId = '' } = useParams();
  const [token] = useState(
    () => consumeTokenFromFragment(workspaceId) ?? recallToken(workspaceId),
  );

  const [hiddenFields, setHiddenFields] = useState<ReadonlySet<string>>(new Set());

  const workspace = useWorkspace(workspaceId, token);
  const rename = useRenameWorkspace(workspaceId, token);
  const records = useRecords(workspaceId, token);
  const correction = useCorrection(workspaceId, token);
  const dashboard = useDashboard(workspaceId, token);

  const toggleField = useCallback((key: string) => {
    setHiddenFields((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const handleCorrect = useCallback(
    (recordId: string, fieldKey: string, value: unknown) => {
      correction.mutate({ recordId, fieldKey, value });
    },
    [correction],
  );

  const handleOpenSource = useCallback(() => {
    // The source viewer is a shared panel (requirements section 3.4) and lands with the
    // chat's citations, which open it the same way. Left unwired rather than faked: a cell
    // that looks clickable and does nothing is worse than one that does not yet.
  }, []);

  if (!token) {
    return (
      <Page>
        <AppHeader active="data" />
        <Main>
          <Message role="alert">
            This workspace needs its access token, and this browser does not have it. Open
            the link you were given in full, including everything after the #.
          </Message>
        </Main>
      </Page>
    );
  }

  const rows = records.data?.records ?? [];
  const fields = workspace.data?.fields ?? [];

  return (
    <Page>
      <AppHeader
        active="data"
        workspace={{
          id: workspaceId,
          label: workspace.data?.label ?? 'Untitled workspace',
          documentCount: workspace.data?.documents?.length ?? 0,
        }}
        onAddDocuments={() => {}}
        onRename={(label) => rename.mutate(label)}
      />

      <Main>
        <TitleBar>
          {/*
            "Data", because that is the screen. It said "Dashboard" over a page that is
            62% table, with a second thing also called Dashboard beside it — two headings
            with one name and neither of them the page.
          */}
          <h1>Data</h1>
        </TitleBar>

        <Columns>
          <Left>
            <SectionHead>
              <h2>Distilled table</h2>
              <p>Click any cell to see its source</p>
            </SectionHead>

            {records.isPending ? (
              <Message>Loading the table…</Message>
            ) : records.isError ? (
              <Message role="alert">{records.error.message}</Message>
            ) : (
              <RecordsTable
                records={rows}
                fields={fields}
                hiddenFields={hiddenFields}
                onToggleField={toggleField}
                onCorrect={handleCorrect}
                onOpenSource={handleOpenSource}
              />
            )}

            <TierLegend />
            <EditHint>
              Double-click a cell to edit. Press Enter to save — the value is then marked
              Verified by a person and re-extraction will not overwrite it.
            </EditHint>

            <DocumentSummary records={rows} />
          </Left>

          <Dashboard state={dashboard.state} onRegenerate={dashboard.regenerate} />
        </Columns>
      </Main>
    </Page>
  );
}
