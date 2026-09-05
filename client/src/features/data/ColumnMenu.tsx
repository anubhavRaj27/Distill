import { MoreHorizontal } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import styled from 'styled-components';

/**
 * The per-column menu.
 *
 * Hand-rolled rather than reached for from Radix, because this is the first menu in the app
 * and pulling a primitive in for one popover would be the wrong order of operations. The
 * behaviour it needs is small and fully covered here: Escape closes, a click outside
 * closes, focus returns to the trigger. When the second and third menus arrive (the source
 * viewer, the composer) this is the point to swap in `radix-ui`'s DropdownMenu and get
 * roving focus and typeahead for free.
 *
 * Rename and "merge into" are the column menu's other two actions in requirements section
 * 3.3. They edit the schema through `PATCH /schema`, so they land with that call rather
 * than being stubbed here as buttons that do nothing.
 */

const Root = styled.div`
  position: relative;
  margin-left: auto;
`;

const Trigger = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  padding: 2px;

  color: ${({ theme }) => theme.color.inkMuted};
  background: none;
  border: 0;
  border-radius: ${({ theme }) => theme.radius.sm};
  cursor: pointer;

  &:hover {
    color: ${({ theme }) => theme.color.ink};
    background: ${({ theme }) => theme.color.line};
  }
`;

const Panel = styled.div`
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  z-index: 20;
  min-width: 176px;

  display: flex;
  flex-direction: column;
  padding: 4px;

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  box-shadow: ${({ theme }) => theme.shadow.raised};
`;

const Item = styled.button`
  appearance: none;
  padding: 7px 10px;

  font-family: inherit;
  font-size: 12px;
  font-weight: 400;
  text-align: left;
  color: ${({ theme }) => theme.color.ink};
  background: none;
  border: 0;
  border-radius: ${({ theme }) => theme.radius.sm};
  cursor: pointer;
  white-space: nowrap;

  &:hover {
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

export interface ColumnMenuProps {
  label: string;
  onHide: () => void;
  onSortAscending: () => void;
  onSortDescending: () => void;
}

export function ColumnMenu({
  label,
  onHide,
  onSortAscending,
  onSortDescending,
}: ColumnMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const run = (action: () => void) => () => {
    action();
    setOpen(false);
  };

  return (
    <Root ref={rootRef}>
      <Trigger
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Options for ${label}`}
        onClick={() => setOpen((current) => !current)}
      >
        <MoreHorizontal size={14} aria-hidden="true" />
      </Trigger>

      {open && (
        <Panel id={menuId} role="menu">
          <Item type="button" role="menuitem" onClick={run(onSortAscending)}>
            Sort ascending
          </Item>
          <Item type="button" role="menuitem" onClick={run(onSortDescending)}>
            Sort descending
          </Item>
          <Item type="button" role="menuitem" onClick={run(onHide)}>
            Hide column
          </Item>
        </Panel>
      )}
    </Root>
  );
}
