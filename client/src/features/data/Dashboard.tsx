import { RefreshCw } from 'lucide-react';
import styled from 'styled-components';

import type { DashboardState } from './useDashboard';

/**
 * The agent-generated dashboard: panels it judged worth showing given the fields, their
 * coverage, and their value distributions (requirements section 3.3).
 *
 * These components are the frame only — title, one-line rationale, states, and the controls
 * around them. The **body of a panel is deliberately not drawn here.** Each panel is an
 * A2UI surface bound to server-computed data (decision D39, product principle 5): the agent
 * emits a query specification, the server evaluates it against `field_values`, and the
 * result is bound into the surface by path. A chart drawn in the client from numbers the
 * client added up would be a different product with a weaker promise, so the slot stays
 * empty until `GET /dashboard` and the A2UI catalog exist.
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

const Controls = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
  min-height: 32px;
`;

const RegenerateButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
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
        <RegenerateButton type="button" disabled={generating} onClick={onRegenerate}>
          <RefreshCw size={12} data-spinning={generating} aria-hidden="true" />
          {generating ? 'Generating…' : 'Regenerate'}
        </RegenerateButton>
        {state.stale && (
          <StaleBadge role="status">
            Stale — {state.newDocuments === 1 ? '1 new document' : `${state.newDocuments} new documents`} added
          </StaleBadge>
        )}
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
        state.panels.map((panel) => (
          <Panel key={panel.id}>
            <PanelTitle>{panel.title}</PanelTitle>
            {/*
              The A2UI surface renders here once the catalog exists. Until then the panel
              shows its rationale, which is real content rather than a placeholder.
            */}
            {panel.rationale && <Rationale>{panel.rationale}</Rationale>}
          </Panel>
        ))}
    </Column>
  );
}
