import { Check, X } from 'lucide-react';
import { useEffect } from 'react';
import styled from 'styled-components';

import { useToasts, type Toast } from './toastStore';

/**
 * The toast stack, mounted once above the routes so a message outlives the screen that
 * raised it. Decision D73.
 *
 * **It is announced, not just drawn.** The region is a polite live region, so the
 * confirmation reaches a screen reader without stealing focus — which is the whole point of
 * a notice nobody has to answer. `aria-atomic` is off: when a second toast arrives, the
 * first has already been read and repeating it would be noise.
 *
 * **It dismisses itself, and can be dismissed.** The timer is the normal path; the close
 * button is there because a timer is a guess about reading speed and someone reading slowly
 * should not be the only one who cannot get rid of it. Hovering pauses nothing, deliberately
 * — a toast that will not leave while the pointer rests nearby is a toast that appears
 * stuck.
 */

const Region = styled.div`
  position: fixed;
  z-index: 40;
  /*
   * Top right, clear of the bottom of the screen entirely.
   *
   * A person often arrives here from an upload (decisions D73, D81), and the bottom of the
   * chat screen is the composer — the box they are about to type in. Bottom centre covered it
   * outright and bottom right still clipped its corner on a narrow window. The top right is
   * the one region no screen in this product puts anything in, and it clears the 64px
   * header.
   */
  top: 80px;
  right: ${({ theme }) => theme.space.xl};

  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: ${({ theme }) => theme.space.sm};

  /* The region spans the width it needs and nothing else, so it never eats clicks. */
  pointer-events: none;
`;

const Item = styled.div`
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.md};
  max-width: min(560px, calc(100vw - 32px));
  padding: 10px 12px 10px 14px;

  font-size: 13px;
  line-height: 1.45;
  color: ${({ theme }) => theme.color.onInk};
  background: ${({ theme }) => theme.color.inkSurface};
  border-radius: ${({ theme }) => theme.radius.md};
  box-shadow: ${({ theme }) => theme.shadow.lifted};

  animation: toast-in ${({ theme }) => theme.motion.settle} both;

  &[data-tone='warning'] {
    background: ${({ theme }) => theme.tier.conflict.color};
  }

  @keyframes toast-in {
    from {
      opacity: 0;
      transform: translateY(-8px) scale(0.98);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
`;

const Glyph = styled.span`
  display: inline-flex;
  flex-shrink: 0;
  opacity: 0.9;
`;

const Message = styled.span`
  min-width: 0;
`;

const Close = styled.button`
  appearance: none;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;

  color: inherit;
  background: transparent;
  border: 0;
  border-radius: ${({ theme }) => theme.radius.sm};
  opacity: 0.7;
  cursor: pointer;

  &:hover {
    opacity: 1;
    background: rgba(255, 255, 255, 0.12);
  }
`;

function ToastRow({ toast }: { toast: Toast }) {
  const dismiss = useToasts((state) => state.dismiss);

  useEffect(() => {
    const timer = window.setTimeout(() => dismiss(toast.id), toast.duration);
    return () => window.clearTimeout(timer);
  }, [dismiss, toast.duration, toast.id]);

  return (
    <Item data-tone={toast.tone}>
      {toast.tone === 'info' && (
        <Glyph>
          <Check size={15} aria-hidden="true" />
        </Glyph>
      )}
      <Message>{toast.message}</Message>
      <Close type="button" aria-label="Dismiss" onClick={() => dismiss(toast.id)}>
        <X size={14} aria-hidden="true" />
      </Close>
    </Item>
  );
}

export function Toasts() {
  const toasts = useToasts((state) => state.toasts);

  return (
    <Region role="status" aria-live="polite" aria-atomic="false">
      {toasts.map((toast) => (
        <ToastRow key={toast.id} toast={toast} />
      ))}
    </Region>
  );
}
