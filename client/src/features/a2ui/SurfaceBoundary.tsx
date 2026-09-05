import { Component, type ErrorInfo, type ReactNode } from 'react';
import styled from 'styled-components';

import { logger } from '../../lib/logger';
import { parseSurface, readRows, type SurfaceRow } from './model';

/**
 * The last line of defence around a generated surface. Implementation section 7.3.
 *
 * A visual is the one thing on this screen whose exact shape nobody reviewed before it
 * appeared: an agent chose the components, the server evaluated a query it had not seen the
 * results of, and this is the first render. `Surface` is written to be total — unknown
 * components are dropped, missing bindings render an em dash, nothing throws — but "written
 * not to throw" and "cannot throw" are different claims, and the cost of being wrong is a
 * blank chat screen instead of a missing chart.
 *
 * So a render error is caught and the fallback below takes over. It is not an apology
 * message: the server always writes the evaluated result into the data model, so the rows
 * are there to be shown as a plain table. A person still gets their answer's figures, in
 * the least clever form available.
 *
 * There is no reset path, on purpose. A boundary that clears its own error on the next
 * update re-renders the component that just threw, which either throws again or flickers.
 * Callers give it a `key` tied to the message instead, so a new answer gets a new boundary
 * and one unrenderable card cannot poison the next.
 */

const Fallback = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.sm};
`;

const Caption = styled.p`
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Table = styled.table`
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;

  th,
  td {
    padding: 5px 8px;
    text-align: left;
    border-bottom: 1px solid ${({ theme }) => theme.color.line};
  }

  th {
    font-weight: 500;
    color: ${({ theme }) => theme.color.inkMuted};
  }

  td:last-child {
    text-align: right;
    font-family: ${({ theme }) => theme.font.mono};
    font-variant-numeric: tabular-nums;
  }
`;

interface Props {
  messages: unknown[];
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export class SurfaceBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The one place `a2ui.fallback` is logged. A spike in it means a builder change on the
    // server is emitting something this catalog cannot render.
    logger.event('a2ui.fallback', {
      detail: error.message,
      componentStack: info.componentStack?.slice(0, 400),
    });
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;

    const parsed = parseSurface(this.props.messages);
    const data = parsed?.data as { result?: { rows?: unknown; title?: unknown } } | undefined;
    const rows = readRows(data?.result?.rows);
    const title = typeof data?.result?.title === 'string' ? data.result.title : null;

    return (
      <Fallback>
        {title && <Caption>{title}</Caption>}
        {rows.length > 0 ? (
          <Table>
            <thead>
              <tr>
                <th scope="col">Label</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row: SurfaceRow, index) => (
                <tr key={index}>
                  <td>{String(row.label ?? '—')}</td>
                  <td>{String(row.value ?? '—')}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <Caption>This answer’s chart could not be drawn. The prose below stands.</Caption>
        )}
      </Fallback>
    );
  }
}
