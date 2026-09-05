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

const Frame = styled.div`
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  box-shadow: ${({ theme }) => theme.shadow.card};
  overflow-x: auto;
`;

const Table = styled.table`
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
`;

const Th = styled.th`
  position: relative;
  padding: 0 12px;
  height: 40px;

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
`;

const HeadInner = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
`;

const SortButton = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;

  font: inherit;
  color: inherit;
  background: none;
  border: 0;
  cursor: pointer;

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }
`;

const Td = styled.td`
  padding: 10px 12px;
  vertical-align: top;
  border-right: 1px solid ${({ theme }) => theme.color.line};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  &:last-child {
    border-right: 0;
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
                        {flexRender(header.column.columnDef.header, header.getContext())}
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
