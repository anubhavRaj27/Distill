import { Fragment } from 'react';
import styled from 'styled-components';

import {
  parseSurface,
  readNumber,
  readProperty,
  readRows,
  type ParsedSurface,
  type SurfaceComponent,
  type SurfaceRow,
} from './model';

/**
 * Rendering an A2UI surface with this application's own components.
 *
 * Requirement A2-02 asks for a catalog the app renders in its own visual language rather
 * than a generic widget kit, and that is what this is: the same paper, rules and ink the
 * table uses, driven entirely by what the server put in the data model. Every figure below
 * is read through a path binding — see `model.ts` for why that separation is the whole
 * safety argument.
 *
 * The renderer is deliberately total. An unknown component was already dropped at parse
 * time; a missing binding renders an em dash; a chart with no rows renders nothing rather
 * than an empty frame. A generated surface is the one part of the interface whose exact
 * shape nobody reviewed before it appeared on screen, so nothing in here may throw.
 */

const Root = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
  min-width: 0;
`;

const Row = styled.div`
  display: flex;
  align-items: flex-start;
  gap: ${({ theme }) => theme.space.lg};
  min-width: 0;
`;

const CardBox = styled.div`
  padding: ${({ theme }) => theme.space.lg};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
`;

const Rule = styled.hr`
  width: 100%;
  height: 1px;
  margin: 0;
  border: 0;
  background: ${({ theme }) => theme.color.line};
`;

const Heading = styled.h3`
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  color: ${({ theme }) => theme.color.ink};
`;

const Body = styled.p`
  font-size: 13px;
  line-height: 1.6;
  color: ${({ theme }) => theme.color.ink};
`;

const Caption = styled.p`
  font-size: 12px;
  line-height: 1.45;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const MetricBlock = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

const MetricValue = styled.span`
  font-family: ${({ theme }) => theme.font.mono};
  font-size: 28px;
  line-height: 1.1;
  color: ${({ theme }) => theme.color.ink};
  font-variant-numeric: tabular-nums;
`;

const MetricLabel = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

/**
 * The chart plot.
 *
 * A baseline rule with columns standing on it, rather than a charting library. The shapes
 * the catalog allows are a bar chart and a line chart of one series each; a dependency that
 * draws those would be several hundred kilobytes to replace forty lines of flexbox, and it
 * would bring its own typography and colours into a design that has both already.
 */
const Plot = styled.div`
  display: flex;
  align-items: flex-end;
  gap: ${({ theme }) => theme.space.lg};
  padding: 0 ${({ theme }) => theme.space.sm};
  height: 150px;
  border-bottom: 1px solid ${({ theme }) => theme.color.lineStrong};
`;

const Column = styled.div`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: ${({ theme }) => theme.space.xs};
  height: 100%;
`;

const Bar = styled.div`
  background: ${({ theme }) => theme.color.stock.heavy};

  /* The largest bar is inked, so the answer's subject is legible without reading a legend. */
  &[data-leading='true'] {
    background: ${({ theme }) => theme.color.inkSurface};
  }
`;

const Legend = styled.div`
  display: flex;
  gap: ${({ theme }) => theme.space.lg};
  padding: 0 ${({ theme }) => theme.space.sm};
`;

const LegendItem = styled.div`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

const SeriesLabel = styled.span`
  font-size: 11px;
  color: ${({ theme }) => theme.color.inkMuted};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const SeriesValue = styled.span`
  font-family: ${({ theme }) => theme.font.mono};
  font-size: 11px;
  color: ${({ theme }) => theme.color.ink};
  font-variant-numeric: tabular-nums;
`;

const Spark = styled.svg`
  width: 100%;
  height: 150px;
  overflow: visible;
  color: ${({ theme }) => theme.color.ink};
`;

const TableScroll = styled.div`
  /* Wide results scroll inside the card rather than widening the whole message. */
  overflow-x: auto;
`;

const Table = styled.table`
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
`;

const Th = styled.th`
  padding: 6px 10px;
  text-align: left;
  font-weight: 500;
  white-space: nowrap;
  color: ${({ theme }) => theme.color.inkMuted};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  &[data-numeric='true'] {
    text-align: right;
  }
`;

const Td = styled.td`
  padding: 6px 10px;
  color: ${({ theme }) => theme.color.ink};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  &[data-numeric='true'] {
    text-align: right;
    font-family: ${({ theme }) => theme.font.mono};
    font-variant-numeric: tabular-nums;
  }
`;

const ABSENT = '—';

/**
 * A figure with its unit, formatted **exactly** as the server formats the same figure in
 * prose (`chat/stream.format_figure`).
 *
 * Grouped thousands; a whole number keeps no decimals, because "184,200" reads as a total
 * where "184,200.00" reads as a ledger line; anything else takes two, because "890.5 USD"
 * is not how money is written. That second half was missing, and it showed the moment the
 * charts appeared: a bar labelled "890.5 USD" sat directly above prose citing "890.50 USD"
 * for the same number. Decision D34 asks for one number to read one way, and two formatters
 * with different rules cannot promise that.
 *
 * The unit is appended rather than turned into a symbol, for the reason `formatValue`
 * gives: a workspace can hold more than one currency and "$" would silently merge them.
 */
function formatFigure(value: unknown, unit?: string): string {
  const numeric = readNumber(value);
  if (numeric === null) return typeof value === 'string' ? value : ABSENT;

  const digits = Number.isInteger(numeric) ? 0 : 2;
  const text = numeric.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return unit ? `${text} ${unit}` : text;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return ABSENT;
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return ABSENT;
}

export interface SurfaceProps {
  /** The message array exactly as the server sent it. */
  messages: unknown[];
  /**
   * Opens the source for a row of a `ResultTable`. Requirement FR-43: provenance has to
   * work inside agent-generated interface too, and every row carries the record ids for it.
   */
  onOpenRecord?: (recordId: string) => void;
}

export function Surface({ messages, onOpenRecord }: SurfaceProps) {
  const parsed = parseSurface(messages);
  if (!parsed) return null;

  return <Node id={parsed.rootId} surface={parsed} onOpenRecord={onOpenRecord} />;
}

interface NodeProps {
  id: string;
  surface: ParsedSurface;
  onOpenRecord?: (recordId: string) => void;
  /** Guards against a `children` cycle in a generated surface. */
  depth?: number;
}

const MAX_DEPTH = 12;

function Node({ id, surface, onOpenRecord, depth = 0 }: NodeProps) {
  if (depth > MAX_DEPTH) return null;

  const component = surface.components.get(id);
  if (!component) return null;

  const children = (component.children ?? []).map((childId) => (
    <Node
      key={childId}
      id={childId}
      surface={surface}
      onOpenRecord={onOpenRecord}
      depth={depth + 1}
    />
  ));

  switch (component.component) {
    case 'Column':
      return <Root>{children}</Root>;
    case 'Row':
      return <Row>{children}</Row>;
    case 'Card':
      return (
        <CardBox>
          <Root>{children}</Root>
        </CardBox>
      );
    case 'Divider':
      return <Rule />;
    case 'Text':
      return <TextNode component={component} data={surface.data} />;
    case 'Metric':
      return <MetricNode component={component} data={surface.data} />;
    case 'BarChart':
      return <BarChartNode component={component} data={surface.data} />;
    case 'LineChart':
      return <LineChartNode component={component} data={surface.data} />;
    case 'ResultTable':
      return (
        <ResultTableNode
          component={component}
          data={surface.data}
          onOpenRecord={onOpenRecord}
        />
      );
  }
}

interface LeafProps {
  component: SurfaceComponent;
  data: unknown;
}

function TextNode({ component, data }: LeafProps) {
  const text = asText(readProperty(component, 'text', data));
  if (text === ABSENT) return null;

  switch (component.variant) {
    case 'h1':
    case 'h2':
    case 'h3':
      return <Heading>{text}</Heading>;
    case 'caption':
      return <Caption>{text}</Caption>;
    default:
      return <Body>{text}</Body>;
  }
}

function MetricNode({ component, data }: LeafProps) {
  const unit = asText(readProperty(component, 'unit', data));
  const value = readProperty(component, 'value', data);
  const label = asText(readProperty(component, 'label', data));

  return (
    <MetricBlock>
      <MetricValue>{formatFigure(value, unit === ABSENT ? undefined : unit)}</MetricValue>
      {label !== ABSENT && <MetricLabel>{label}</MetricLabel>}
    </MetricBlock>
  );
}

/** Rows plus the keys the component said to read them by, and the largest value seen. */
function series(component: SurfaceComponent, data: unknown) {
  const rows = readRows(readProperty(component, 'rows', data));
  const xKey = typeof component.xKey === 'string' ? component.xKey : 'label';
  const yKey = typeof component.yKey === 'string' ? component.yKey : 'value';
  const unitRaw = asText(readProperty(component, 'unit', data));
  const unit = unitRaw === ABSENT ? undefined : unitRaw;

  const points = rows.map((row: SurfaceRow) => ({
    label: asText(row[xKey]),
    value: readNumber(row[yKey]),
  }));

  // Bars are drawn against the largest value, not against zero-to-max of the axis, so a
  // set of similar figures still shows its differences.
  const peak = points.reduce((max, point) => Math.max(max, point.value ?? 0), 0);
  return { points, peak, unit };
}

const PLOT_HEIGHT = 120;

function BarChartNode({ component, data }: LeafProps) {
  const { points, peak, unit } = series(component, data);
  if (points.length === 0) return null;

  return (
    <div>
      <Plot>
        {points.map((point, index) => (
          <Column key={`${point.label}-${index}`}>
            <Bar
              data-leading={point.value !== null && peak > 0 && point.value === peak}
              style={{
                // A present-but-tiny value still gets a visible sliver; a null value gets
                // nothing at all, because absent and zero are different facts.
                height:
                  point.value === null
                    ? 0
                    : Math.max(2, peak > 0 ? (point.value / peak) * PLOT_HEIGHT : 0),
              }}
            />
          </Column>
        ))}
      </Plot>
      <Legend>
        {points.map((point, index) => (
          <LegendItem key={`${point.label}-legend-${index}`}>
            <SeriesLabel title={point.label}>{point.label}</SeriesLabel>
            <SeriesValue>{formatFigure(point.value, unit)}</SeriesValue>
          </LegendItem>
        ))}
      </Legend>
    </div>
  );
}

const LINE_VIEWBOX = { width: 600, height: 150 };

function LineChartNode({ component, data }: LeafProps) {
  const { points, peak, unit } = series(component, data);
  const plotted = points.filter((point) => point.value !== null);
  if (plotted.length < 2) return null;

  const step = LINE_VIEWBOX.width / (points.length - 1 || 1);
  const scale = peak > 0 ? (LINE_VIEWBOX.height - 12) / peak : 0;

  const path = points
    .map((point, index) => {
      if (point.value === null) return null;
      const x = index * step;
      const y = LINE_VIEWBOX.height - 6 - point.value * scale;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter((pair): pair is string => pair !== null)
    .join(' ');

  return (
    <div>
      <Spark
        viewBox={`0 0 ${LINE_VIEWBOX.width} ${LINE_VIEWBOX.height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Line chart of ${points.length} points`}
      >
        <polyline
          points={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      </Spark>
      <Legend>
        {/* Ends only. A tick per point is unreadable past a handful of buckets. */}
        <LegendItem>
          <SeriesLabel>{points[0]!.label}</SeriesLabel>
          <SeriesValue>{formatFigure(points[0]!.value, unit)}</SeriesValue>
        </LegendItem>
        <LegendItem style={{ alignItems: 'flex-end' }}>
          <SeriesLabel>{points[points.length - 1]!.label}</SeriesLabel>
          <SeriesValue>{formatFigure(points[points.length - 1]!.value, unit)}</SeriesValue>
        </LegendItem>
      </Legend>
    </div>
  );
}

interface TableColumn {
  key: string;
  label: string;
  type?: string;
}

function readColumns(component: SurfaceComponent): TableColumn[] {
  const raw = component.columns;
  if (!Array.isArray(raw)) return [];

  return raw.flatMap((entry) => {
    if (typeof entry !== 'object' || entry === null) return [];
    const { key, label, type } = entry as Record<string, unknown>;
    if (typeof key !== 'string') return [];
    return [
      {
        key,
        label: typeof label === 'string' ? label : key,
        type: typeof type === 'string' ? type : undefined,
      },
    ];
  });
}

const NUMERIC_TYPES = new Set(['number', 'currency', 'integer']);

const ProvenanceCell = styled.button`
  appearance: none;
  padding: 0;
  font: inherit;
  color: inherit;
  text-align: inherit;
  background: none;
  border: 0;
  border-bottom: 1px dotted ${({ theme }) => theme.color.lineStrong};
  cursor: pointer;

  &:hover {
    border-bottom-color: ${({ theme }) => theme.color.ink};
  }
`;

function ResultTableNode({
  component,
  data,
  onOpenRecord,
}: LeafProps & { onOpenRecord?: (recordId: string) => void }) {
  const columns = readColumns(component);
  const rows = readRows(readProperty(component, 'rows', data));
  if (columns.length === 0 || rows.length === 0) return null;

  return (
    <TableScroll>
      <Table>
        <thead>
          <tr>
            {columns.map((column) => (
              <Th
                key={column.key}
                data-numeric={NUMERIC_TYPES.has(column.type ?? '')}
                scope="col"
              >
                {column.label}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            // Requirement FR-43: every row carries the records behind it, so a cell inside
            // a generated surface opens the same source viewer a table cell does.
            const recordId = Array.isArray(row.record_ids) ? row.record_ids[0] : undefined;

            return (
              <tr key={index}>
                {columns.map((column) => {
                  const numeric = NUMERIC_TYPES.has(column.type ?? '');
                  const text = numeric
                    ? formatFigure(row[column.key])
                    : asText(row[column.key]);

                  return (
                    <Td key={column.key} data-numeric={numeric}>
                      {recordId && onOpenRecord ? (
                        <ProvenanceCell
                          type="button"
                          onClick={() => onOpenRecord(recordId)}
                          title="Open the source for this row"
                        >
                          {text}
                        </ProvenanceCell>
                      ) : (
                        <Fragment>{text}</Fragment>
                      )}
                    </Td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </Table>
    </TableScroll>
  );
}
