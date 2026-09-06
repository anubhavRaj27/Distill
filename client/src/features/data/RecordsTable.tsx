import {
  createSortedRowModel,
  flexRender,
  rowSortingFeature,
  sortFns,
  tableFeatures,
  useTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { ArrowDown, ArrowUp, FileSpreadsheet, FileText, Image as ImageIcon } from 'lucide-react';
import { useMemo, useState } from 'react';
import styled from 'styled-components';

import type { components } from '../../api/schema';
import { ColumnMenu } from './ColumnMenu';
import { ValueCell } from './cells/ValueCell';
import { formatValue } from './cells/formatValue';

type RecordRow = components['schemas']['Record'];
type FieldSpec = components['schemas']['FieldSpec'];

/**
 * TanStack Table v9 stitches feature modules, row-model factories, and the sort-function
 * registry together statically, so only the code a table actually uses is bundled. Sorting
 * is all this table needs; filtering, grouping, and pagination stay out of the bundle.
 *
 * Declared at module scope, as the library asks: rebuilding it per render would rebuild the
 * table's whole feature set on every keystroke.
 */
const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns,
});

type Column = ColumnDef<typeof features, RecordRow>;

/**
 * The distilled table: one row per document, one column per unified field.
 *
 * TanStack Table in headless mode, because every cell needs its own renderer for type and
 * confidence and no styled table library would let that happen cleanly. It is not
 * virtualised: v2 cut that (requirements section 0) on the grounds that a workspace holds
 * tens of documents, not thousands.
 */

/**
 * The table's window, and the thing that scrolls.
 *
 * It used to scroll sideways only and grow downwards without limit, which put both of the
 * table's controls out of reach at once on a real workspace: the horizontal scrollbar sat
 * at the bottom of a 1,200px-tall table, a page-scroll away from the columns it moves, and
 * the header row was long gone by the third document. A bounded window fixes both, and it
 * is what makes position:sticky mean anything — sticky positions against the nearest
 * scrolling ancestor, so without a scrollport of its own there is nothing for a header row
 * to stick to.
 *
 * A viewport fraction rather than a pixel height: the cap only has to leave the page's own
 * chrome and the summary below it visible, and a short table never reaches it.
 */
const Frame = styled.div`
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  box-shadow: ${({ theme }) => theme.shadow.card};
  overflow: auto;
  max-height: 70vh;
`;

/**
 * max-content, not 100%, and the cells earn their width.
 *
 * At width:100% the browser has to fit every column into the frame, and with a schema of
 * thirty columns that means squeezing each one to its minimum — which, next to the cells'
 * overflow-wrap, is one character wide. "Northwind Trading Company" was being rendered as
 * "North wind Tradin g Comp any" in a column 130px wide, in a table that was 4,000px wide
 * anyway and scrolling sideways regardless. Letting the columns take their natural width
 * and capping them at a readable measure gives the same scrolling and legible words.
 */
const Table = styled.table`
  width: max-content;
  min-width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 11px;
`;

/**
 * The header row, pinned to the top of the frame.
 *
 * border-collapse:separate above is what makes this possible at all: collapsed borders
 * belong to the table rather than to the cell, and they do not travel with a sticky cell —
 * the row detaches and leaves its rules behind. Separate borders, drawn on one side each,
 * look identical and stay attached.
 */
const Th = styled.th`
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 0 12px;
  height: 40px;
  max-width: 240px;

  font-size: 11px;
  font-weight: 500;
  text-align: left;
  color: ${({ theme }) => theme.color.inkMuted};
  background: ${({ theme }) => theme.color.paperSunken};
  border-right: 1px solid ${({ theme }) => theme.color.line};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};
  white-space: nowrap;

  &:last-child {
    border-right: 0;
  }

  /*
   * Which document a row is remains readable however far right the table is scrolled.
   * Thirty columns in, a row of values with no name on it is unreadable.
   */
  &:first-child {
    left: 0;
    z-index: 3;
  }
`;

const HeadInner = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
`;

const SortButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  min-width: 0;

  font: inherit;
  color: inherit;
  background: none;
  border: 0;
  cursor: pointer;

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }

  svg {
    flex-shrink: 0;
  }
`;

/**
 * The column's name, and the part of the header that gives way.
 *
 * A label is whatever the documents called the field, which can be a sentence. The header
 * row does not wrap, so without a cut here a long label runs straight out of its cell and
 * across its neighbour. It needs its own element: the button is a flex container, and
 * text-overflow does not reach a bare text node inside one.
 */
const Label = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Td = styled.td`
  padding: 10px 12px;
  min-width: 96px;
  max-width: 240px;
  vertical-align: top;
  border-right: 1px solid ${({ theme }) => theme.color.line};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  &:last-child {
    border-right: 0;
  }

  &:first-child {
    position: sticky;
    left: 0;
    z-index: 1;
    background: ${({ theme }) => theme.color.paperRaised};
    border-right: 1px solid ${({ theme }) => theme.color.line};
  }
`;

const Tr = styled.tr`
  &:last-child ${Td} {
    border-bottom: 0;
  }
`;

const DocumentName = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: ${({ theme }) => theme.color.ink};

  svg {
    flex-shrink: 0;
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

const Empty = styled.div`
  padding: ${({ theme }) => theme.space.section};
  text-align: center;
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

/** Which glyph a row wears, from its filename. Cosmetic, so an unknown type is fine. */
function documentIcon(filename: string) {
  const extension = filename.slice(filename.lastIndexOf('.') + 1).toLowerCase();
  if (['xlsx', 'csv'].includes(extension)) return FileSpreadsheet;
  if (['png', 'jpg', 'jpeg'].includes(extension)) return ImageIcon;
  return FileText;
}

export interface RecordsTableProps {
  records: RecordRow[];
  fields: FieldSpec[];
  hiddenFields: ReadonlySet<string>;
  onToggleField: (key: string) => void;
  onCorrect: (recordId: string, fieldKey: string, value: unknown) => void;
  onOpenSource: (recordId: string, fieldKey: string) => void;
}

export function RecordsTable({
  records,
  fields,
  hiddenFields,
  onToggleField,
  onCorrect,
  onOpenSource,
}: RecordsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [editing, setEditing] = useState<{ recordId: string; fieldKey: string } | null>(
    null,
  );

  const columns = useMemo<Column[]>(() => {
    const documentColumn: Column = {
      id: 'document',
      header: 'Document',
      accessorFn: (row) => row.document_name,
      cell: ({ row }) => {
        const Icon = documentIcon(row.original.document_name);
        return (
          <DocumentName>
            <Icon size={14} aria-hidden="true" />
            {row.original.document_name}
          </DocumentName>
        );
      },
    };

    const fieldColumns = fields
      .filter((field) => !hiddenFields.has(field.key))
      .map<Column>((field) => ({
        id: field.key,
        header: field.label,
        /*
         * Sorting reads the formatted text rather than the raw value, so a column of money
         * sorts the way it is displayed. The exception is numbers and currency, where the
         * numeric magnitude is what a person means by "sort by total".
         */
        accessorFn: (row) => {
          const value = row.values?.[field.key]?.value;
          if (value == null) return null;
          if (field.type === 'currency' && typeof value === 'object' && 'amount' in value) {
            return Number((value as { amount: number }).amount);
          }
          if (field.type === 'number') return Number(value);
          return formatValue(value, field.type);
        },
        sortUndefined: 'last',
        cell: ({ row }) => {
          const isEditing =
            editing !== null &&
            editing.recordId === row.original.id &&
            editing.fieldKey === field.key;
          return (
            <ValueCell
              value={row.original.values?.[field.key]}
              type={field.type}
              editing={isEditing}
              onStartEdit={() =>
                setEditing({ recordId: row.original.id, fieldKey: field.key })
              }
              onCancelEdit={() => setEditing(null)}
              onCommit={(next) => {
                setEditing(null);
                onCorrect(row.original.id, field.key, next);
              }}
              onOpenSource={() => onOpenSource(row.original.id, field.key)}
            />
          );
        },
      }));

    return [documentColumn, ...fieldColumns];
  }, [editing, fields, hiddenFields, onCorrect, onOpenSource]);

  // Generics are explicit: inference falls back to the library's `RowData` default
  // otherwise, and every row callback silently degrades to `any[]`.
  const table = useTable<typeof features, RecordRow>({
    features,
    data: records,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    // A row is a document; keeping its identity stable means a streamed update repaints a
    // cell rather than remounting the row under the person's cursor.
    getRowId: (row) => row.id,
  });

  if (fields.length === 0) {
    return (
      <Frame>
        <Empty>
          No schema yet. The first documents are still being read — the columns appear as
          soon as the schema is inferred.
        </Empty>
      </Frame>
    );
  }

  return (
    <Frame>
      <Table>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const sorted = header.column.getIsSorted();
                return (
                  <Th key={header.id} scope="col">
                    <HeadInner>
                      <SortButton
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        aria-label={`Sort by ${String(header.column.columnDef.header)}`}
                      >
                        {sorted === 'asc' && <ArrowUp size={12} aria-hidden="true" />}
                        {sorted === 'desc' && <ArrowDown size={12} aria-hidden="true" />}
                        <Label>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </Label>
                      </SortButton>

                      {header.column.id !== 'document' && (
                        <ColumnMenu
                          label={String(header.column.columnDef.header)}
                          onHide={() => onToggleField(header.column.id)}
                          onSortAscending={() => header.column.toggleSorting(false)}
                          onSortDescending={() => header.column.toggleSorting(true)}
                        />
                      )}
                    </HeadInner>
                  </Th>
                );
              })}
            </tr>
          ))}
        </thead>

        <tbody>
          {table.getRowModel().rows.map((row) => (
            <Tr key={row.id}>
              {row.getAllCells().map((cell) => (
                <Td key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </Td>
              ))}
            </Tr>
          ))}
        </tbody>
      </Table>

      {records.length === 0 && <Empty>No documents have finished being read yet.</Empty>}
    </Frame>
  );
}
