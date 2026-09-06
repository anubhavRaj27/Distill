import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, authHeader, toFailure } from '../../api/client';

/**
 * The document behind a citation: its page dimensions, and one rendered page as an image.
 *
 * **Why the image is fetched rather than put in a `src`.** Every route authorises with a
 * bearer token (decision D7) and `<img>` sends no headers, so the browser's own request
 * would arrive unauthenticated and 401. The bytes are fetched with the header and handed to
 * the element as a blob URL instead. The alternative — a token in the query string — puts
 * the only credential this product has into history, logs and referrer headers.
 *
 * **Why the dimensions come separately.** Highlight boxes are in page *points*; the image
 * is in pixels at whatever DPI the server rendered. `DocumentDetail.pages[].width_pt` is
 * the divisor that turns one into the other, and the server's own comment on that field
 * says so: the viewer divides the width it actually rendered by `width_pt`. Nothing here
 * needs to know the DPI, which is the point of the arrangement.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? '';

export interface PageGeometry {
  index: number;
  width_pt: number;
  height_pt: number;
}

function readPages(pages: { [key: string]: unknown }[]): PageGeometry[] {
  return pages.flatMap((page) => {
    const { index, width_pt, height_pt } = page;
    if (
      typeof index !== 'number' ||
      typeof width_pt !== 'number' ||
      typeof height_pt !== 'number'
    ) {
      return [];
    }
    return [{ index, width_pt, height_pt }];
  });
}

/** Page geometry for one document. Cached: it does not change once parsed. */
export function useDocumentPages(
  workspaceId: string,
  documentId: string | null,
  token: string | null,
) {
  return useQuery({
    queryKey: ['document', workspaceId, documentId],
    enabled: Boolean(token && documentId),
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        '/api/v1/workspaces/{workspace_id}/documents/{document_id}',
        {
          params: {
            path: { workspace_id: workspaceId, document_id: documentId! },
            header: authHeader(token!),
          },
        },
      );
      if (error || !data) throw toFailure(error, response?.status);
      return { filename: data.filename, pages: readPages(data.pages ?? []) };
    },
  });
}

export interface PageImage {
  url: string | null;
  isPending: boolean;
  error: string | null;
}

/**
 * One rendered page, as a blob URL.
 *
 * The URL is revoked when the page changes or the viewer closes. Skipping that leaks the
 * decoded image for the life of the tab, which for a viewer someone clicks through twenty
 * citations with is not a rounding error.
 */
export function usePageImage(
  workspaceId: string,
  documentId: string | null,
  pageIndex: number | null,
  token: string | null,
): PageImage {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setPending] = useState(false);

  useEffect(() => {
    if (!token || !documentId || pageIndex === null) {
      setUrl(null);
      setError(null);
      return;
    }

    // Guards a race: two citations clicked quickly resolve out of order, and without this
    // the slower response would overwrite the newer page.
    const controller = new AbortController();
    let objectUrl: string | null = null;

    setPending(true);
    setError(null);

    void (async () => {
      try {
        const response = await fetch(
          `${BASE_URL}/api/v1/workspaces/${workspaceId}/documents/${documentId}` +
            `/pages/${pageIndex}/image`,
          { headers: authHeader(token), signal: controller.signal },
        );

        if (!response.ok) {
          // A page that was never rendered is a real state, not a crash: an image-only
          // format that failed OCR has no page image to show.
          setError(
            response.status === 404
              ? 'This page has not been rendered, so it cannot be shown here.'
              : `The page image could not be loaded (${response.status}).`,
          );
          return;
        }

        objectUrl = URL.createObjectURL(await response.blob());
        if (controller.signal.aborted) return;
        setUrl(objectUrl);
      } catch (failure) {
        if (controller.signal.aborted) return;
        setError(
          failure instanceof Error
            ? failure.message
            : 'The page image could not be loaded.',
        );
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    })();

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, pageIndex, token, workspaceId]);

  return { url, isPending, error };
}
