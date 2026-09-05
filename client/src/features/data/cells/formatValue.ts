import type { components } from '../../../api/schema';

type FieldType = components['schemas']['FieldType'];

/**
 * Turning a stored value into something a person reads.
 *
 * Every type has one presentation and it lives here, so the table, the chat's result
 * tables, and the source viewer cannot drift apart on how money or a date looks. The
 * conversions in `server/app/domain/values.py` are the other half of this contract.
 *
 * Nothing here guesses. A value the server sent as null is rendered as an em dash, never as
 * zero or an empty string, because "this document does not say" and "this document says
 * nothing was spent" are different facts and the table must not blur them.
 */

export const ABSENT = '—';

interface CurrencyValue {
  amount: number | string;
  currency?: string;
}

function isCurrency(value: unknown): value is CurrencyValue {
  return typeof value === 'object' && value !== null && 'amount' in value;
}

/**
 * Money is formatted with grouped thousands and exactly two decimals, and the ISO code is
 * kept beside it rather than turned into a symbol: a workspace can hold several currencies
 * at once, and "$" would silently merge them.
 */
function formatCurrency(value: CurrencyValue): string {
  const amount = typeof value.amount === 'string' ? Number(value.amount) : value.amount;
  if (!Number.isFinite(amount)) return ABSENT;

  const formatted = amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return value.currency ? `${formatted} ${value.currency}` : formatted;
}

/**
 * Dates arrive as ISO strings and are shown in a fixed, unambiguous form rather than the
 * locale's short format: `03/04/2024` means two different days on two sides of an ocean,
 * and this is a document a person is checking against a source.
 */
function formatDate(value: string): string {
  const parsed = new Date(value.length <= 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(parsed.getTime())) return value;

  return parsed.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export function formatValue(value: unknown, type: FieldType): string {
  if (value === null || value === undefined) return ABSENT;

  switch (type) {
    case 'currency':
      return isCurrency(value) ? formatCurrency(value) : String(value);

    case 'date':
      return typeof value === 'string' ? formatDate(value) : String(value);

    case 'number':
      return typeof value === 'number'
        ? value.toLocaleString(undefined, { maximumFractionDigits: 4 })
        : String(value);

    case 'boolean':
      // Rendered as a mark by the cell, but a text form is still needed for the
      // accessible name and for export.
      return value ? 'Yes' : 'No';

    case 'string_list':
      return Array.isArray(value) ? value.join(', ') : String(value);

    case 'string':
    case 'enum':
    default:
      return String(value);
  }
}

/** What goes back into an editor when a person starts typing over a value. */
export function toEditableText(value: unknown, type: FieldType): string {
  if (value === null || value === undefined) return '';
  if (type === 'currency' && isCurrency(value)) return String(value.amount);
  if (type === 'string_list' && Array.isArray(value)) return value.join(', ');
  if (type === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

/**
 * Parse an edit back into the stored representation.
 *
 * Deliberately conservative: anything it cannot parse confidently is returned as a string
 * and the server has the final say. A client that guessed here could turn a typo into a
 * number and mark it human-verified, which is the one status the model may never overwrite.
 */
export function fromEditableText(
  text: string,
  type: FieldType,
  previous: unknown,
): unknown {
  const trimmed = text.trim();
  if (trimmed === '') return null;

  switch (type) {
    case 'number': {
      const parsed = Number(trimmed.replace(/,/g, ''));
      return Number.isFinite(parsed) ? parsed : trimmed;
    }
    case 'currency': {
      const parsed = Number(trimmed.replace(/[,\s]/g, ''));
      if (!Number.isFinite(parsed)) return trimmed;
      const currency = isCurrency(previous) ? previous.currency : undefined;
      return { amount: parsed, currency };
    }
    case 'boolean': {
      const lowered = trimmed.toLowerCase();
      if (['true', 'yes', 'y', 'paid'].includes(lowered)) return true;
      if (['false', 'no', 'n', 'unpaid'].includes(lowered)) return false;
      return trimmed;
    }
    case 'string_list':
      return trimmed
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean);
    default:
      return trimmed;
  }
}
