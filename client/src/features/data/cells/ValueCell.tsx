import { useState } from 'react';
import styled from 'styled-components';

import type { components } from '../../../api/schema';
import { TierMark } from './TierMark';
import { ABSENT, formatValue, fromEditableText, toEditableText } from './formatValue';

type FieldValue = components['schemas']['FieldValue'];
type FieldType = components['schemas']['FieldType'];

/**
 * One cell of the distilled table.
 *
 * Three jobs, in priority order: show the value in the shape its type deserves, show how
 * much it should be trusted, and get out of the way of a correction. Clicking opens the
 * source viewer; double-clicking (or Enter) starts an edit, because the common case is
 * checking a value against its source, not retyping it.
 */

const Wrapper = styled.div`
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: ${({ theme }) => theme.space.sm};
  min-height: 20px;
`;

const Body = styled.div`
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

const Text = styled.span<{ $mono?: boolean; $muted?: boolean }>`
  font-family: ${({ $mono, theme }) => ($mono ? theme.font.mono : 'inherit')};
  font-size: ${({ $mono }) => ($mono ? '11px' : '12px')};
  line-height: 1.4;
  color: ${({ $muted, theme }) => ($muted ? theme.color.inkMuted : theme.color.ink)};
  /*
   * break-word, not anywhere. They differ in one place that matters here: anywhere
   * counts the break opportunities when the browser works out a cell's minimum width, so a
   * column of company names could be squeezed to one character and every word in it split
   * down the middle. break-word breaks a word only when the word itself will not fit,
   * which is the case it is actually for.
   */
  overflow-wrap: break-word;
`;

const Chips = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
`;

const Chip = styled.span`
  padding: 1px 6px;
  font-size: 11px;
  background: ${({ theme }) => theme.color.paperSunken};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  white-space: nowrap;
`;

const BooleanMark = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.tier.verified.color};

  &[data-value='false'] {
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

/** The conflict presentation: both readings shown, neither silently chosen. */
const Conflict = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 9px;
  line-height: 1.5;
  color: ${({ theme }) => theme.tier.conflict.color};

  button {
    appearance: none;
    padding: 0;
    font-family: inherit;
    font-size: 10px;
    color: ${({ theme }) => theme.color.ink};
    background: none;
    border: 0;
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }
`;

const Editor = styled.input`
  width: 100%;
  height: 28px;
  padding: 0 8px;

  font-family: inherit;
  font-size: 12px;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.ink};
  border-radius: ${({ theme }) => theme.radius.sm};
  outline: none;
  box-shadow: 0 0 0 2px rgba(26, 34, 56, 0.2);
`;

export interface ValueCellProps {
  value: FieldValue | undefined;
  type: FieldType;
  editing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onCommit: (next: unknown) => void;
  onOpenSource: () => void;
}

/**
 * The editor, mounted only while a cell is being edited.
 *
 * Its own component on purpose. When the draft lived in the cell and was populated by an
 * effect, the input's first render was empty — so `select()` on focus selected nothing, the
 * effect then filled the value in behind the caret, and typing appended: correcting
 * "Freight" to "Freight & Logistics" produced "FreightFreight & Logistics". Mounting a
 * fresh component means the value is right in the first render, and focus-then-select does
 * what it looks like it does.
 */
function CellEditor({
  initial,
  onCommit,
  onCancel,
}: {
  initial: string;
  onCommit: (text: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);

  return (
    <Editor
      value={draft}
      aria-label="Edit value"
      autoFocus
      onFocus={(event) => event.currentTarget.select()}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={onCancel}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          onCommit(draft);
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          onCancel();
        }
      }}
    />
  );
}

export function ValueCell({
  value,
  type,
  editing,
  onStartEdit,
  onCancelEdit,
  onCommit,
  onOpenSource,
}: ValueCellProps) {
  if (editing) {
    return (
      <CellEditor
        initial={toEditableText(value?.value, type)}
        onCancel={onCancelEdit}
        onCommit={(text) => onCommit(fromEditableText(text, type, value?.value))}
      />
    );
  }

  // A field the extractor never produced for this document, which is not the same as a
  // field it looked for and found absent. Both render as an em dash; only the tier differs.
  if (!value) {
    return (
      <Wrapper onDoubleClick={onStartEdit}>
        <Text $muted>{ABSENT}</Text>
      </Wrapper>
    );
  }

  const tier = value.tier;
  const conflicted = tier === 'conflict' && value.model_value != null;

  return (
    <Wrapper
      onClick={onOpenSource}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onStartEdit();
      }}
    >
      <Body>
        {conflicted ? (
          <>
            <Text $mono>Model: {formatValue(value.model_value, type)}</Text>
            <Text $mono>Human: {formatValue(value.value, type)}</Text>
            <Conflict>
              <span>
                {/* The glyph is repeated in words right beside it, per the colour rule. */}
                {'⌁'} Conflicting values{' '}
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onStartEdit();
                  }}
                >
                  Resolve
                </button>
              </span>
            </Conflict>
          </>
        ) : (
          renderBody(value, type)
        )}
      </Body>

      <TierMark tier={tier} />
    </Wrapper>
  );
}

function renderBody(value: FieldValue, type: FieldType) {
  const absent = value.value === null || value.value === undefined;

  if (type === 'boolean') {
    if (absent) return <BooleanMark data-value="false">{'○'}</BooleanMark>;
    return (
      <BooleanMark data-value={String(Boolean(value.value))}>
        {value.value ? '✓' : '○'}
      </BooleanMark>
    );
  }

  if (type === 'string_list' && Array.isArray(value.value) && value.value.length > 0) {
    return (
      <Chips>
        {(value.value as string[]).map((entry) => (
          <Chip key={entry}>{entry}</Chip>
        ))}
      </Chips>
    );
  }

  const mono = type === 'currency' || type === 'date' || type === 'number';
  return (
    <Text $mono={mono} $muted={absent}>
      {formatValue(value.value, type)}
    </Text>
  );
}
