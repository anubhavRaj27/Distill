import { AlertCircle, Check, Image as ImageIcon } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import styled from 'styled-components';

import { extensionOf } from '../../../lib/files';
import type { UploadTask } from '../../../lib/upload';

/**
 * One document as a sheet of paper, for the spiral on the upload screen.
 *
 * The upstream spiral takes image URLs, and the obvious way to fill it would be stock
 * pictures of documents from the web. That would be a lie on a screen whose entire subject
 * is the person's own files, it would put a network fetch in the way of a one-command
 * offline demo, and it would show a stranger's invoice while yours was uploading.
 *
 * So the cards are the real files:
 *
 * - **An image is its own thumbnail.** The browser already holds the `File`, so a blob URL
 *   renders the actual picture before a single byte has reached the server.
 * - **Everything else is drawn.** A PDF, DOCX or TXT gets ruled lines with a heavier title
 *   rule; a CSV or XLSX gets a small grid with a filled header row. Not a facsimile of the
 *   file — an honest sketch of its *shape*, which is the distinction the product is about.
 *
 * Status rides on the card the same way it rides on `UploadRow`: never colour alone, always
 * a mark as well.
 */

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg']);
const SHEET_EXTENSIONS = new Set(['csv', 'xlsx']);

type Preview = 'image' | 'sheet' | 'text';

function previewFor(extension: string): Preview {
  if (IMAGE_EXTENSIONS.has(extension)) return 'image';
  if (SHEET_EXTENSIONS.has(extension)) return 'sheet';
  return 'text';
}

const Sheet = styled.div`
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  box-shadow: ${({ theme }) => theme.shadow.raised};

  &[data-phase='failed'] {
    border-color: ${({ theme }) => theme.tier.conflict.color};
  }

  /* Not yet sent, so not yet real. Reads as paper still on its way. */
  &[data-phase='waiting'] {
    opacity: 0.72;
  }
`;

const Body = styled.div`
  position: relative;
  flex: 1;
  min-height: 0;
  padding: 14px 12px;
  background: ${({ theme }) => theme.color.paperRaised};
`;

const Thumbnail = styled.img`
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  background: ${({ theme }) => theme.color.paperSunken};
`;

/** Ruled lines standing in for prose. Widths vary, or it reads as a barcode. */
const Line = styled.div`
  height: 4px;
  margin-bottom: 7px;
  border-radius: 1px;
  background: ${({ theme }) => theme.color.stock.mid};

  &[data-title='true'] {
    height: 7px;
    margin-bottom: 12px;
    background: ${({ theme }) => theme.color.stock.heavy};
  }
`;

const PROSE_WIDTHS = ['62%', '100%', '92%', '97%', '78%', '100%', '88%', '54%'];

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 3px;
`;

const Cell = styled.div`
  height: 11px;
  border-radius: 1px;
  background: ${({ theme }) => theme.color.stock.light};

  &[data-header='true'] {
    background: ${({ theme }) => theme.color.stock.heavy};
  }
`;

/** An image the browser would not decode. Says "picture" without pretending to be one. */
const Fallback = styled.div`
  display: grid;
  place-items: center;
  height: 100%;
  color: ${({ theme }) => theme.color.stock.heavy};
`;

const Footer = styled.div`
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 9px;

  background: ${({ theme }) => theme.color.paper};
  border-top: 1px solid ${({ theme }) => theme.color.line};
`;

const Badge = styled.span`
  flex-shrink: 0;
  padding: 1px 5px;

  font-family: ${({ theme }) => theme.font.mono};
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: ${({ theme }) => theme.color.onInk};
  background: ${({ theme }) => theme.color.inkSurface};
  border-radius: 2px;
`;

const Name = styled.span`
  min-width: 0;
  font-size: 10px;
  line-height: 1.3;
  color: ${({ theme }) => theme.color.inkMuted};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

/** Top-right corner, over the preview. Sized to read at 74% scale at the back of the ring. */
const Stamp = styled.span`
  position: absolute;
  top: 7px;
  right: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;

  color: ${({ theme }) => theme.color.onInk};
  background: ${({ theme }) => theme.tier.verified.color};
  border-radius: ${({ theme }) => theme.radius.pill};

  &[data-phase='failed'] {
    background: ${({ theme }) => theme.tier.conflict.color};
  }
`;

/**
 * A blob URL for an image file, revoked when the card goes away.
 *
 * Returns null for anything that is not an image, and for an image the browser refuses to
 * decode — a `.png` that is really something else, which the server would reject anyway.
 */
function useThumbnail(file: File, enabled: boolean): string | null {
  // Derived rather than held in state: a `useState` filled from an effect would render the
  // card once without its picture and once with, for a value that is a pure function of
  // the file. The effect exists only to hand the URL back when the card goes away.
  const url = useMemo(
    () =>
      enabled && typeof URL.createObjectURL === 'function'
        ? URL.createObjectURL(file)
        : null,
    [enabled, file],
  );

  useEffect(() => {
    if (!url) return;
    return () => URL.revokeObjectURL(url);
  }, [url]);

  return url;
}

export function DocumentCard({ task }: { task: UploadTask }) {
  const extension = extensionOf(task.file.name);
  const preview = previewFor(extension);
  const thumbnail = useThumbnail(task.file, preview === 'image');
  const [broken, setBroken] = useState(false);

  return (
    <Sheet data-phase={task.phase}>
      <Body>
        {preview === 'image' && thumbnail && !broken && (
          <Thumbnail src={thumbnail} alt="" onError={() => setBroken(true)} />
        )}

        {preview === 'image' && (!thumbnail || broken) && (
          <Fallback>
            <ImageIcon size={26} strokeWidth={1.4} aria-hidden="true" />
          </Fallback>
        )}

        {preview === 'sheet' && (
          <Grid>
            {Array.from({ length: 16 }, (_, index) => (
              <Cell key={index} data-header={index < 4} />
            ))}
          </Grid>
        )}

        {preview === 'text' &&
          PROSE_WIDTHS.map((width, index) => (
            <Line key={index} data-title={index === 0} style={{ width }} />
          ))}

        {(task.phase === 'ready' || task.phase === 'failed') && (
          <Stamp data-phase={task.phase}>
            {task.phase === 'failed' ? <AlertCircle size={12} /> : <Check size={12} />}
          </Stamp>
        )}
      </Body>

      <Footer>
        <Badge>{extension.toUpperCase()}</Badge>
        <Name>{task.file.name}</Name>
      </Footer>
    </Sheet>
  );
}
