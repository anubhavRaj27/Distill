import { create } from 'zustand';

/**
 * Transient confirmations, held outside the component tree.
 *
 * The store exists for one reason the component tree cannot solve: the thing worth
 * confirming is often the last thing a screen does before it goes away. "Your documents
 * arrived" is raised by the upload screen as it navigates to the conversation, so a notice
 * rendered by that screen would unmount in the same tick it appeared — the same problem
 * `pendingUploads` solves for a file selection, and solved the same way.
 *
 * What a toast is for here, and what it is not: it confirms something that already
 * happened and needs no response. Anything a person has to act on belongs on the screen —
 * a refused file gets `RejectionNotice` under the drop zone, a failed document keeps its
 * row in the library. A toast that carries the only copy of something important is a
 * message that disappears while you are reading it.
 */

export type ToastTone = 'info' | 'warning';

export interface Toast {
  id: string;
  message: string;
  tone: ToastTone;
  /** Milliseconds on screen. Warnings sit longer, being worse news. */
  duration: number;
}

interface ToastStore {
  toasts: Toast[];
  show: (message: string, options?: { tone?: ToastTone; duration?: number }) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

const DEFAULT_DURATION = 5000;
const WARNING_DURATION = 9000;

/** Most recent last, and never more than this many: a stack is not a log. */
const MAX_TOASTS = 3;

let counter = 0;

export const useToasts = create<ToastStore>((set) => ({
  toasts: [],

  show: (message, options = {}) => {
    counter += 1;
    const id = `toast-${counter}`;
    const tone = options.tone ?? 'info';
    const toast: Toast = {
      id,
      message,
      tone,
      duration:
        options.duration ?? (tone === 'warning' ? WARNING_DURATION : DEFAULT_DURATION),
    };
    set((state) => ({ toasts: [...state.toasts, toast].slice(-MAX_TOASTS) }));
    return id;
  },

  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),

  clear: () => set({ toasts: [] }),
}));
