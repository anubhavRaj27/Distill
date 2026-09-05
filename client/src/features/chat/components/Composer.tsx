import { ArrowUp } from 'lucide-react';
import { useCallback, useLayoutEffect, useRef } from 'react';
import styled from 'styled-components';

/**
 * The question box.
 *
 * A `textarea` rather than an `input`, because questions about a pile of documents are not
 * always one line, and a field that scrolls sideways while you write is hostile. It grows
 * to fit what has been typed and stops at a ceiling.
 *
 * Enter sends and Shift+Enter breaks the line — the convention every chat interface uses,
 * so anything else would be a small surprise on the product's main screen.
 */

const Form = styled.form`
  position: sticky;
  bottom: 0;
  z-index: 1;
  width: 100%;
  padding-bottom: ${({ theme }) => theme.space.xl};
  /* The thread scrolls beneath the composer; without a ground it would show through. */
  background: linear-gradient(
    to bottom,
    transparent,
    ${({ theme }) => theme.color.paper} 20%
  );
`;

const Shell = styled.div`
  display: flex;
  align-items: flex-end;
  gap: ${({ theme }) => theme.space.sm};
  padding: ${({ theme }) => theme.space.sm};

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  box-shadow: ${({ theme }) => theme.shadow.raised};

  &:focus-within {
    border-color: ${({ theme }) => theme.color.lineStrong};
  }
`;

const Field = styled.textarea`
  flex: 1;
  min-width: 0;
  max-height: 180px;
  padding: 6px 8px;

  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  color: ${({ theme }) => theme.color.ink};
  background: transparent;
  border: 0;
  outline: none;
  resize: none;

  &::placeholder {
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

const Send = styled.button`
  appearance: none;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;

  color: ${({ theme }) => theme.color.onInk};
  background: ${({ theme }) => theme.color.inkSurface};
  border: 0;
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.inkSurfaceHover};
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }
`;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onAsk: (question: string) => void;
  /** Shut while an answer is being written: one question at a time. */
  disabled?: boolean;
  placeholder?: string;
}

/**
 * Controlled rather than holding its own draft, because something outside it writes into
 * the box: picking a suggested question fills it in and leaves it there to be edited. With
 * local state that becomes an effect copying a prop into state on every change, which is
 * one render behind and a well-known source of stale-input bugs.
 */
export function Composer({
  value,
  onChange,
  onAsk,
  disabled = false,
  placeholder = 'Ask about these documents…',
}: ComposerProps) {
  const field = useRef<HTMLTextAreaElement>(null);

  /*
   * Grow to fit what has been typed.
   *
   * Three things here are each load-bearing, and the first version had none of them:
   *
   * - **Reset to `auto` before measuring.** `scrollHeight` of an element with an explicit
   *   height includes that height, so without the reset the box can only ever grow.
   * - **Hand an empty box back to CSS.** An inline height is only ever an override for
   *   content that has outgrown one line. Leaving one on an empty field is what pinned the
   *   composer open at its 180px ceiling on mount: the measurement ran before the layout
   *   had settled, read a stretched element, and then never remeasured, because the value
   *   had not changed.
   * - **Clamp to the CSS ceiling.** A measurement taken at a bad moment then costs a
   *   scrollbar rather than a composer that has eaten the conversation.
   *
   * `useLayoutEffect` so the height is right in the same paint as the text, rather than
   * one frame behind it while someone is typing.
   */
  useLayoutEffect(() => {
    const element = field.current;
    if (!element) return;

    element.style.height = 'auto';
    if (value === '') {
      element.style.height = '';
      return;
    }

    const ceiling = Number.parseFloat(getComputedStyle(element).maxHeight);
    const wanted = Number.isFinite(ceiling)
      ? Math.min(element.scrollHeight, ceiling)
      : element.scrollHeight;
    element.style.height = `${wanted}px`;
  }, [value]);

  const submit = useCallback(() => {
    const question = value.trim();
    if (!question || disabled) return;
    onAsk(question);
    onChange('');
  }, [disabled, onAsk, onChange, value]);

  return (
    <Form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Shell>
        <Field
          ref={field}
          rows={1}
          value={value}
          placeholder={placeholder}
          aria-label="Ask about these documents"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            // `isComposing` guards an IME: mid-composition Enter commits the candidate
            // word, and sending there would fire on a half-typed question.
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <Send
          type="submit"
          disabled={disabled || value.trim() === ''}
          aria-label="Send question"
        >
          <ArrowUp size={16} aria-hidden="true" />
        </Send>
      </Shell>
    </Form>
  );
}
