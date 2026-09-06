import { RefreshCw } from 'lucide-react';
import styled from 'styled-components';

import { Surface } from '../a2ui/Surface';
import { SurfaceBoundary } from '../a2ui/SurfaceBoundary';
import type { DashboardState } from './useDashboard';

/**
 * The agent-generated dashboard: panels it judged worth showing given the fields, their
 * coverage, and their value distributions (requirements section 3.3).
 *
 * A panel's body is an **A2UI surface**, rendered by the same component that renders a
 * chat visual (decision D28, product principle 5): the agent emits a query specification,
 * the server evaluates it against `field_values`, and the result is bound into the surface
 * by path. A chart drawn in the client from numbers the client added up would be a
 * different product with a weaker promise.
 *
 * That slot sat empty until September 6, 2026 — the panels arrived with their surfaces
 * attached and this file rendered the rationale and dropped them, so the product had a
 * dashboard with no charts in it. It is one line of rendering, and the
 * comment that used to be here said it was waiting for a catalog that already existed.
 *
 * What is real today: the states. Not generated, generating, ready, stale, and failed are
 * exactly the situations requirements section 3.5 asks the dashboard area to survive
 * without taking the table down with it.
 */

const Column = styled.aside`
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
`;

/**
 * The column's own heading, and the two controls that belong to it.
 *
 * It matches the shape of the table's heading on the other side — a name and a line saying
 * what you are looking at — for a plain layout reason as well as a reading one: the two
 * columns of this screen are a grid row, and a bare 32px strip of buttons on one side
 * against a 38px heading on the other started the panels and the table at different
 * heights, which reads as a mistake rather than as a column.
 */
const Head = styled.div`
  margin-right: auto;
  min-width: 0;

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

const Controls = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
  min-height: 38px;
`;

const RegenerateButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 4px 10px;

  font-family: inherit;
  font-size: 11px;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.paperSunken};
  }
  &:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  svg[data-spinning='true'] {
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
`;

const StaleBadge = styled.span`
  padding: 4px 8px;
  font-size: 10px;
  color: ${({ theme }) => theme.tier.medium.color};
  background: ${({ theme }) => theme.color.paperSunken};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

const Panel = styled.section`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
  padding: ${({ theme }) => theme.space.lg};

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  box-shadow: ${({ theme }) => theme.shadow.raised};
`;

const PanelTitle = styled.h3`
  font-family: ${({ theme }) => theme.font.display};
  font-weight: 400;
  font-size: 15px;
  color: ${({ theme }) => theme.color.ink};
`;

/**
 * The one-line explanation under every panel.
 *
 * Requirements section 3.3 asks for it by name, and it is the panel's most important line:
 * "Six of eight documents carry a total and a vendor, so spend by vendor is answerable"
 * tells a sceptical person what the chart is *not* counting, which is the thing a chart
 * otherwise hides.
 */
const Rationale = styled.p`
  font-size: 11px;
  line-height: 1.45;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const RetryButton = styled.button`
  appearance: none;
  align-self: flex-start;
  padding: 4px 10px;

  font-family: inherit;
  font-size: 11px;
  color: ${({ theme }) => theme.color.ink};
  background: none;
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
`;

export interface DashboardProps {
  state: DashboardState;
  onRegenerate: () => void;
}

export function Dashboard({ state, onRegenerate }: DashboardProps) {
  const generating = state.status === 'generating';

  return (
    <Column aria-label="Dashboard">
      <Controls>
        <Head>
          <h2>Dashboard</h2>
          <p>Panels the agent chose from what the documents actually contain</p>
        </Head>
        {state.stale && (
          <StaleBadge role="status">
            Stale — {state.newDocuments === 1 ? '1 new document' : `${state.newDocuments} new documents`} added
          </StaleBadge>
        )}
        <RegenerateButton type="button" disabled={generating} onClick={onRegenerate}>
          <RefreshCw size={12} data-spinning={generating} aria-hidden="true" />
          {generating ? 'Generating…' : 'Regenerate'}
        </RegenerateButton>
      </Controls>

      {state.status === 'failed' && (
        <Panel>
          <PanelTitle>Dashboard</PanelTitle>
          <Rationale role="alert">{state.error}</Rationale>
          <RetryButton type="button" onClick={onRegenerate}>
            Retry
          </RetryButton>
        </Panel>
      )}

      {state.status === 'absent' && (
        <Panel>
          <PanelTitle>No panels yet</PanelTitle>
          <Rationale>
            The dashboard is generated once the first batch of documents has been read.
            Regenerate to ask for it now.
          </Rationale>
        </Panel>
      )}

      {state.status === 'generating' && (
        <Panel>
          <PanelTitle>Working out what is worth showing</PanelTitle>
          <Rationale>
            Reading the field statistics and choosing panels. The table is unaffected.
          </Rationale>
        </Panel>
      )}

      {state.status === 'ready' &&
        state.panels.map((panel, index) => (
          /*
           * Keyed by position, deliberately. A panel has no identifier of its own: the set
           * is regenerated wholesale, so "the second panel" is as stable as it gets and a
           * missing `id` would otherwise key every panel `undefined`.
           */
          <Panel key={`${panel.title}-${index}`}>
            <PanelTitle>{panel.title}</PanelTitle>
            {Array.isArray(panel.surface) && panel.surface.length > 0 && (
              <SurfaceBoundary messages={panel.surface}>
                <Surface messages={panel.surface} />
              </SurfaceBoundary>
            )}
            {panel.rationale && <Rationale>{panel.rationale}</Rationale>}
          </Panel>
        ))}
    </Column>
  );
}
