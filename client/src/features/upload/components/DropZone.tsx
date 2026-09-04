import { useCallback, useId, useRef, useState } from 'react';

import styled from 'styled-components';

import { ACCEPT_ATTRIBUTE, SUPPORTED_EXTENSIONS } from '../../../lib/files';

const Zone = styled.div`
  position: relative;
  width: 100%;

  border: 1px dashed ${({ theme }) => theme.color.lineStrong};
  border-radius: ${({ theme }) => theme.radius.sm};
  background: rgba(255, 255, 255, 0.4);

  padding: ${({ theme }) => theme.space.xxl} ${({ theme }) => theme.space.xl};
  text-align: center;

  transition:
    border-color ${({ theme }) => theme.motion.quick},
    background-color ${({ theme }) => theme.motion.quick};

  /*
   * The dragging state is driven by a data attribute rather than an interpolated prop, so
   * styled-components generates two classes for this component rather than one per state
   * change during a drag. Same rule the table cells will follow.
   */
  &[data-dragging='true'] {
    border-color: ${({ theme }) => theme.color.ink};
    background: ${({ theme }) => theme.color.paperRaised};
  }
`;

const Stack = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
`;

const Glyph = styled.svg`
  width: 32px;
  height: 32px;
  color: ${({ theme }) => theme.color.ink};
`;

const Headline = styled.p`
  font-size: 18px;
  font-weight: 600;
  color: ${({ theme }) => theme.color.ink};
`;

const Detail = styled.p`
  font-size: 14px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

/**
 * The whole zone is one large label for a visually hidden file input. A keyboard user
 * tabs to a real `<input type="file">` and presses Enter; a pointer user clicks anywhere
 * in the rectangle or drops onto it. No custom key handling, no `role="button"` on a div,
 * and the native picker for free.
 */
const HiddenInput = styled.input`
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
`;

export interface DropZoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  /**
   * The hidden input, exposed so the "Choose files" button below the zone opens the same
   * native picker instead of duplicating one.
   */
  inputRef?: React.RefObject<HTMLInputElement | null>;
}

export function DropZone({ onFiles, disabled = false, inputRef }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const describedBy = useId();

  /*
   * `dragenter` and `dragleave` fire for every child element the pointer crosses, so a
   * boolean set from the events alone flickers. Counting depth is the standard fix and it
   * lives in a ref, because it is bookkeeping rather than rendered state.
   */
  const depth = useRef(0);

  const handleDragEnter = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    depth.current += 1;
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    depth.current = Math.max(0, depth.current - 1);
    if (depth.current === 0) setDragging(false);
  }, []);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    // Without this the browser navigates to the dropped file and the workspace is lost.
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      if (disabled) return;

      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length > 0) onFiles(files);
    },
    [disabled, onFiles],
  );

  const handleChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      if (files.length > 0) onFiles(files);
      // Reset, so choosing the same file twice in a row still fires a change event.
      event.target.value = '';
    },
    [onFiles],
  );

  return (
    <Zone
      data-dragging={dragging}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <Stack>
        <Glyph viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <path
            d="M6.5 18a4.5 4.5 0 0 1-.53-8.97 6 6 0 0 1 11.65-1.5A4.25 4.25 0 0 1 18 18"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M12 21v-8m0 0-3 3m3-3 3 3" strokeLinecap="round" strokeLinejoin="round" />
        </Glyph>
        <Headline>Drop files to begin</Headline>
        <Detail id={describedBy}>
          PDF, scans, spreadsheets, and Word documents — any mix, any format
        </Detail>
      </Stack>

      <HiddenInput
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTRIBUTE}
        disabled={disabled}
        onChange={handleChange}
        aria-label={`Choose documents to upload. Supported formats: ${SUPPORTED_EXTENSIONS.join(', ')}.`}
        aria-describedby={describedBy}
      />
    </Zone>
  );
}
