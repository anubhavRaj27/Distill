import { Upload } from 'lucide-react';
import { useCallback, useId, useRef, useState } from 'react';
import styled from 'styled-components';

import { ACCEPT_ATTRIBUTE, SUPPORTED_EXTENSIONS } from '../../../lib/files';

const Zone = styled.div`
  position: relative;
  width: 640px;
  max-width: 100%;
  height: 220px;

  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: ${({ theme }) => theme.space.md};

  /*
   * A translucent surface over the first-run screen's aurora, not an opaque card on top of
   * it. Decision D89.
   *
   * The blur is what makes this legible rather than merely pretty: it turns the ribbons
   * behind into broad fields of colour, so what sits under the prompt changes slowly across
   * the panel instead of moving under the words. The text in here is the ink colour, the
   * strongest in the palette, which is what lets the panel carry its own contrast without
   * the page's scrim behind it.
   *
   * No backticks in this comment, and none in any other inside a styled block: this is a
   * template literal, and one would end it. GlobalStyle carries the same warning.
   */
  background: ${({ theme }) => theme.color.glass};
  backdrop-filter: blur(22px) saturate(1.15);
  border: 1px dashed ${({ theme }) => theme.color.lineStrong};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;

  transition:
    border-color ${({ theme }) => theme.motion.quick},
    background-color ${({ theme }) => theme.motion.quick};

  /*
   * Drag state rides on a data attribute rather than an interpolated prop, so this
   * component compiles to two classes rather than one per state change during a drag.
   * The same rule the data table's cells will follow.
   */
  &[data-dragging='true'] {
    border-color: ${({ theme }) => theme.color.ink};
    /* Firming up as well as darkening: a file is over it, so it stops being a window. */
    background: ${({ theme }) => theme.color.glassDragging};
  }

  svg {
    color: ${({ theme }) => theme.color.ink};
  }
`;

const Prompt = styled.span`
  font-size: 14px;
  color: ${({ theme }) => theme.color.ink};
`;

const ChooseButton = styled.button`
  appearance: none;
  margin-top: ${({ theme }) => theme.space.xs};
  padding: 8px 16px;

  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.lineStrong};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.paperSunken};
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
`;

/**
 * The real file input, visually hidden but present in the tab order.
 *
 * It is not stretched invisibly across the whole zone. Doing that would put a transparent
 * input on top of the "Choose files" button and swallow its clicks, and it would give the
 * zone two overlapping click targets with one accessible name between them. Instead the
 * input stays small and hidden, the button drives it, and the zone forwards stray pointer
 * clicks to it as a convenience.
 */
const HiddenInput = styled.input`
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
`;

export interface DropZoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export function DropZone({ onFiles, disabled = false }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const describedBy = useId();

  /*
   * `dragenter` and `dragleave` fire for every child element the pointer crosses, so a
   * boolean set straight from those events flickers. Counting depth is the fix, and it
   * lives in a ref because it is bookkeeping rather than rendered state.
   */
  const depth = useRef(0);

  const openPicker = useCallback(() => {
    if (!disabled) inputRef.current?.click();
  }, [disabled]);

  const handleZoneClick = useCallback(
    (event: React.MouseEvent) => {
      // The button inside the zone drives the picker itself; without this guard its click
      // would bubble up here and open the dialog a second time.
      if ((event.target as HTMLElement).closest('button')) return;
      openPicker();
    },
    [openPicker],
  );

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
      onClick={handleZoneClick}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <Upload size={28} strokeWidth={1.5} aria-hidden="true" />
      <Prompt id={describedBy}>Drag files here or click to browse</Prompt>

      <ChooseButton type="button" onClick={openPicker} disabled={disabled}>
        Choose files
      </ChooseButton>

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
