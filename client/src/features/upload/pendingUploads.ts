import { create } from 'zustand';

import type { RejectedFile } from '../../lib/files';

/**
 * The files chosen on screen 1, held across the navigation into the workspace.
 *
 * A `File` is a handle to bytes on disk. It cannot be serialised into a URL, and React
 * Router's history state has to survive `structuredClone` into the browser's session
 * history, so neither route params nor location state can carry a selection. A small store
 * outside the component tree can.
 *
 * This is deliberately transient: it holds a selection for the moment between "workspace
 * created" and "upload screen mounted", and is cleared as soon as the screen has taken it.
 * Nothing else should read it. If the person reloads the upload screen mid-flight the store
 * is empty, and the screen falls back to the documents the server already has — which is
 * the honest thing to show, since the browser genuinely no longer holds those files.
 */

interface PendingUploads {
  workspaceId: string | null;
  files: File[];
  /**
   * Files refused on screen 1, carried so the refusal survives the navigation.
   *
   * Without this they are reported on a screen the person is leaving in the same tick, so
   * the notice flashes and disappears — which is indistinguishable from the files having
   * been accepted. Requirement FR-03 asks for a refusal the person can actually read.
   */
  rejected: RejectedFile[];
  stage: (workspaceId: string, files: File[], rejected: RejectedFile[]) => void;
  clear: () => void;
}

export const usePendingUploads = create<PendingUploads>((set) => ({
  workspaceId: null,
  files: [],
  rejected: [],
  stage: (workspaceId, files, rejected) => set({ workspaceId, files, rejected }),
  clear: () => set({ workspaceId: null, files: [], rejected: [] }),
}));
