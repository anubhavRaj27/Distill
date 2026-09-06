import { Monitor, Moon, Sun } from 'lucide-react';
import styled from 'styled-components';

import { useAppearance, type ThemePreference } from './appearance';

/**
 * Light, automatic, dark — as a segmented control in the header.
 *
 * **Why three and not a toggle.** A two-state switch has to store a resolved palette, and
 * the moment it does, "follow my system" stops being reachable: a visitor who taps it once
 * at noon is pinned to light for good and never sees the page turn over in the evening.
 * Showing the automatic setting as its own segment is what keeps it a place you can go back
 * to rather than a default you can only lose.
 *
 * **Why a segmented control and not a menu.** There is one already, right beside it: the
 * three screens. Two rows of the same shape in the same bar teach each other, and a control
 * whose whole content is three icons costs less room open than a menu button costs closed.
 *
 * The buttons carry `aria-pressed` rather than radio semantics. They are three ordinary
 * buttons in the ordinary tab order, which is what a person reaching this with a keyboard
 * expects from a bar full of buttons — a radiogroup would put them behind arrow keys and
 * gain nothing, since there is nothing here to type into.
 */

const Group = styled.div`
  flex-shrink: 0;
  display: flex;
  align-items: center;
  overflow: hidden;

  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

const Segment = styled.button`
  appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 28px;
  padding: 0;

  color: ${({ theme }) => theme.color.inkMuted};
  background: transparent;
  border: 0;
  border-right: 1px solid ${({ theme }) => theme.color.line};
  cursor: pointer;
  transition:
    color ${({ theme }) => theme.motion.quick},
    background-color ${({ theme }) => theme.motion.quick};

  &:last-child {
    border-right: 0;
  }

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }

  /* The chosen segment, drawn exactly like the current screen tab beside it. */
  &[aria-pressed='true'] {
    background: ${({ theme }) => theme.color.inkSurface};
    color: ${({ theme }) => theme.color.onInk};
  }
`;

const OPTIONS: ReadonlyArray<{
  preference: ThemePreference;
  label: string;
  Icon: typeof Sun;
}> = [
  { preference: 'light', label: 'Light', Icon: Sun },
  { preference: 'system', label: 'Match my system', Icon: Monitor },
  { preference: 'dark', label: 'Dark', Icon: Moon },
];

export function AppearanceSwitch() {
  const { preference, setPreference } = useAppearance();

  return (
    <Group role="group" aria-label="Appearance">
      {OPTIONS.map(({ preference: option, label, Icon }) => (
        <Segment
          key={option}
          type="button"
          title={label}
          aria-label={label}
          aria-pressed={preference === option}
          onClick={() => setPreference(option)}
        >
          <Icon size={14} aria-hidden="true" />
        </Segment>
      ))}
    </Group>
  );
}
