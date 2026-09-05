import { Download, X } from 'lucide-react';
import { useLayoutEffect, useRef, useState } from 'react';
import styled from 'styled-components';

import { authHeader } from '../../api/client';
import type { BBox } from '../chat/answerStream';
import { highlightStyle } from './geometry';
import { useDocumentPages, usePageImage } from './usePageImage';

/**
 * The source, with the cited passage lit up. Product principle 4.
 *
 * This is the panel that makes every other claim in the product checkable: a citation, a
 * table cell and a figure inside a generated chart all open the same viewer, and all of
 * them land on the words the value came from rather than on page one of the file.
 *
 * The overlay's arithmetic is the whole trick and it is deliberately simple. The server
 * gives boxes in page **points** and, separately, the page's size in points. The image
 * renders at whatever width the panel allows. Scale is therefore rendered width divided by
 * `width_pt`, measured from the element after layout — so the highlight tracks the image
 * through a resize with no DPI anywhere in the client.
 */

const Panel = styled.aside`
  flex-shrink: 0;
  width: 380px;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.lg};
  padding: ${({ theme }) => theme.space.xl};
  overflow-y: auto;

  background: ${({ theme }) => theme.color.paperRaised};
  border-left: 1px solid ${({ theme }) => theme.color.line};
`;

const Head = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: ${({ theme }) => theme.space.md};
`;

const Title = styled.h2`
  font-family: ${({ theme }) => theme.font.display};
  font-size: 17px;
  font-weight: 400;
  color: ${({ theme }) => theme.color.ink};
`;

const CloseButton = styled.button`
  appearance: none;
  display: inline-flex;
  padding: 4px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: none;
  border: 0;
  cursor: pointer;

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }
`;

const Stage = styled.div`
  position: relative;
  background: ${({ theme }) => theme.color.paperSunken};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  overflow: hidden;
`;

const PageImage = styled.img`
  display: block;
  width: 100%;
  height: auto;
`;

/**
 * One highlight rectangle.
 *
 * Multiply rather than a solid fill, so the words underneath stay readable — a highlighter
 * over text, which is what a person checking a figure needs, rather than a block covering
 * it. `mix-blend-mode` is the only way to get that without compositing the image itself.
 */
const Highlight = styled.div`
  position: absolute;
  background: rgba(214, 178, 74, 0.42);
  mix-blend-mode: multiply;
  border-radius: 1px;
  pointer-events: none;
`;

const Placeholder = styled.div`
  display: grid;
  place-items: center;
  min-height: 220px;
  padding: ${({ theme }) => theme.space.lg};

  font-size: 12px;
  text-align: center;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Excerpt = styled.p`
  font-size: 13px;
  line-height: 1.55;
  color: ${({ theme }) => theme.color.ink};
`;

const Meta = styled.p`
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const DownloadLink = styled.button`
  appearance: none;
  align-self: flex-start;
  padding: 0;

  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  font-size: 12px;
  color: ${({ theme }) => theme.color.ink};
  background: none;
  border: 0;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
`;

/** What the viewer is asked to show. Any caller that can produce this can open it. */
export interface SourceTarget {
  documentId: string;
  filename: string;
  pageIndex: number | null;
  boxes: BBox[];
  excerpt: string;
  /** The footnote number, when the target came from a citation. */
  n?: number;
}

export interface SourceViewerProps {
  workspaceId: string;
  token: string | null;
  target: SourceTarget;
  onClose: () => void;
}

export function SourceViewer({
  workspaceId,
  token,
  target,
  onClose,
}: SourceViewerProps) {
  const document_ = useDocumentPages(workspaceId, target.documentId, token);
  const page = usePageImage(workspaceId, target.documentId, target.pageIndex, token);

  const imageRef = useRef<HTMLImageElement>(null);
  const [scale, setScale] = useState(0);

  const geometry = document_.data?.pages.find(
    (entry) => entry.index === target.pageIndex,
  );

  /*
   * Measured after layout rather than computed from a fixed panel width, because the image
   * is `width: 100%` of a panel that can be resized and can carry a scrollbar. Reading it
   * in `useLayoutEffect` puts the highlight on screen in the same paint as the image, so
   * it never appears a frame late in the wrong place.
   */
  useLayoutEffect(() => {
    const element = imageRef.current;
    if (!element || !geometry || geometry.width_pt <= 0) return;

    const measure = () => setScale(element.clientWidth / geometry.width_pt);
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [geometry, page.url]);

  return (
    <Panel aria-label="Source viewer">
      <Head>
        <Title>Source</Title>
        <CloseButton type="button" onClick={onClose} aria-label="Close source viewer">
          <X size={16} aria-hidden="true" />
        </CloseButton>
      </Head>

      {page.url ? (
        <Stage>
          <PageImage
            ref={imageRef}
            src={page.url}
            alt={`Page ${(target.pageIndex ?? 0) + 1} of ${target.filename}`}
            onLoad={() => {
              const element = imageRef.current;
              if (element && geometry && geometry.width_pt > 0) {
                setScale(element.clientWidth / geometry.width_pt);
              }
            }}
          />
          {target.boxes.map((box, index) => {
            const style = highlightStyle(box, scale);
            return style ? <Highlight key={index} style={style} /> : null;
          })}
        </Stage>
      ) : (
        <Placeholder role={page.error ? 'alert' : undefined}>
          {page.isPending
            ? 'Loading the page…'
            : (page.error ??
              // A digest citation has no page: it resolves through the extracted values'
              // provenance instead (server/app/chat/citations.py).
              'This passage comes from the extracted values rather than from a single page.')}
        </Placeholder>
      )}

      {target.excerpt && <Excerpt>“…{target.excerpt}…”</Excerpt>}

      <Meta>
        {target.filename}
        {target.pageIndex !== null && ` · p. ${target.pageIndex + 1}`}
      </Meta>

      {token && (
        <DownloadLink
          type="button"
          onClick={() => void openOriginal(workspaceId, target, token)}
        >
          <Download size={12} aria-hidden="true" />
          Open the original
        </DownloadLink>
      )}
    </Panel>
  );
}

/**
 * Open the original file in a new tab.
 *
 * A plain `<a href>` cannot do this for the same reason `<img src>` cannot show the page:
 * the browser's own request carries no Authorization header. So the file is fetched with
 * one and opened as a blob. The URL is revoked on a timer rather than immediately, because
 * revoking it before the new tab has read it leaves that tab blank.
 */
async function openOriginal(
  workspaceId: string,
  target: SourceTarget,
  token: string,
): Promise<void> {
  const base = import.meta.env.VITE_API_URL ?? '';
  const response = await fetch(
    `${base}/api/v1/workspaces/${workspaceId}/documents/${target.documentId}/file`,
    { headers: authHeader(token) },
  );
  if (!response.ok) return;

  const url = URL.createObjectURL(await response.blob());
  window.open(url, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
