import { Plus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import styled from 'styled-components';

import { AppearanceSwitch } from '../ui/AppearanceSwitch';
import { Wordmark } from '../ui/Wordmark';

/**
 * The application chrome: identity on the left, the three-screen switch on the right.
 *
 * There are three screens and only three — Upload, Chat, Data — so they are a segmented
 * control that is always visible rather than a navigation menu. A user can always see the
 * whole product from anywhere in it, which is the point of having cut everything else.
 *
 * The same header serves the first-run screen and the workspace screens. Before a workspace
 * exists there is nothing to chat about and no data to show, so those two tabs render
 * disabled rather than disappearing: the shape of the product stays legible from the very
 * first screen, and the disabled state teaches what happens after you upload.
 */

const Bar = styled.header`
  height: 64px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.xl};
  padding: 0 ${({ theme }) => theme.space.xl};

  /* Narrow enough that the gaps themselves are worth reclaiming before the name is. */
  @media (max-width: 900px) {
    gap: ${({ theme }) => theme.space.md};
    padding: 0 ${({ theme }) => theme.space.lg};
  }

  background: ${({ theme }) => theme.color.paperRaised};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};
`;

/**
 * The wordmark, as the way back to the documents.
 *
 * A logo in the top left is a home link everywhere else, and this product's home is the
 * screen the documents are on. Inside a workspace it goes to that workspace's Upload screen
 * rather than to the front door, which would mint nothing and show a drop zone for a
 * workspace the person already has.
 *
 * Its accessible name is the visible one, "Distill", which is what a home link should be
 * called.
 */
const Home = styled(Link)`
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 4px 6px;
  margin-left: -6px;

  text-decoration: none;
  border-radius: ${({ theme }) => theme.radius.sm};
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover {
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

const Divider = styled.div`
  flex-shrink: 0;
  width: 1px;
  height: 32px;
  background: ${({ theme }) => theme.color.line};
`;

/**
 * The name and document count. The one part of the bar that gives way.
 *
 * Everything else here is a fixed-size control — the wordmark, the three-screen switch, the
 * add button — and with every child refusing to shrink the bar simply overflowed the window
 * below about 820px wide, taking "Add documents" off the right edge and giving the whole
 * document a horizontal scrollbar. A name is the one thing that can be shortened without
 * losing a control, and it already ellipsises.
 */
const Workspace = styled.div`
  flex: 0 1 auto;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
`;

/**
 * The workspace's name, and a way to change it.
 *
 * A button rather than a text field sitting there permanently: this is a label that is read
 * far more often than it is written, and an input in the chrome of every screen invites
 * being typed in by accident. It looks like text until you point at it.
 */
const WorkspaceName = styled.button`
  appearance: none;
  max-width: 320px;
  min-width: 0;
  padding: 1px 4px;
  margin-left: -4px;

  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.25;
  text-align: left;
  color: ${({ theme }) => theme.color.ink};
  background: transparent;
  border: 0;
  border-radius: ${({ theme }) => theme.radius.sm};
  cursor: text;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

const NameInput = styled.input`
  max-width: 320px;
  padding: 1px 4px;
  margin-left: -4px;

  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.25;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.lineStrong};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

const WorkspaceMeta = styled.span`
  font-size: 12px;
  line-height: 1.25;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Spacer = styled.div`
  flex: 1;
`;

const Tabs = styled.nav`
  flex-shrink: 0;
  display: flex;
  align-items: center;
  overflow: hidden;

  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
`;

/**
 * One segment.
 *
 * Which screen is current is passed in rather than inferred from URL matching. Chat lives
 * at both `/w/{id}` and `/w/{id}/chat` (requirements section 3.2), so a link-matching rule
 * would leave the bare workspace URL with no tab lit at all. The caller knows which screen
 * it is; asking it is simpler and cannot disagree with itself.
 *
 * Styling keys off `aria-current`, so the visual state and the state announced to a screen
 * reader are the same fact rather than two facts that can drift.
 */
const tabSurface = `
  appearance: none;
  display: inline-flex;
  align-items: center;
  padding: 6px 16px;

  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
  text-decoration: none;
  white-space: nowrap;
  background: transparent;
  border: 0;
  border-right: 1px solid var(--line);

  &:last-child {
    border-right: 0;
  }
`;

const TabLink = styled(Link)`
  ${tabSurface}
  color: ${({ theme }) => theme.color.inkMuted};
  cursor: pointer;
  transition: color ${({ theme }) => theme.motion.quick};

  &:hover {
    color: ${({ theme }) => theme.color.ink};
  }

  &[aria-current='page'] {
    background: ${({ theme }) => theme.color.inkSurface};
    color: ${({ theme }) => theme.color.onInk};
  }
`;

const TabDisabled = styled.span`
  ${tabSurface}
  color: ${({ theme }) => theme.color.inkMuted};
  opacity: 0.45;
  cursor: not-allowed;
`;

const AddButton = styled.button`
  appearance: none;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;

  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

export type Screen = 'upload' | 'chat' | 'data';

export interface AppHeaderProps {
  /** Absent on the first-run screen, where no workspace exists yet. */
  workspace?: {
    id: string;
    label: string;
    documentCount: number;
  };
  /** Which of the three screens is showing. */
  active?: Screen;
  /** Rendered only inside a workspace. Requirement FR-06. */
  onAddDocuments?: () => void;
  /**
   * Renames the workspace. Absent on a screen that cannot write, in which case the name is
   * shown as plain text rather than as a control that does nothing.
   */
  onRename?: (label: string) => void;
}

export function AppHeader({
  workspace,
  active = 'upload',
  onAddDocuments,
  onRename,
}: AppHeaderProps) {
  const inWorkspace = workspace !== undefined;
  const current = (screen: Screen) => (active === screen ? ('page' as const) : undefined);

  /*
   * The draft lives here and is seeded when editing opens, not synchronised with the
   * workspace label. A label that arrives from the server while someone is typing — which
   * it does, since the first name is generated a few seconds in — must not overwrite what
   * they are in the middle of writing.
   */
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = () => {
    const next = draft.trim();
    setEditing(false);
    if (!next || next === workspace?.label) return;
    onRename?.(next);
  };

  return (
    <Bar>
      <Home to={workspace ? `/w/${workspace.id}/upload` : '/'}>
        <Wordmark />
      </Home>

      {inWorkspace && (
        <>
          <Divider />
          <Workspace>
            {editing && onRename ? (
              <NameInput
                ref={inputRef}
                value={draft}
                aria-label="Workspace name"
                maxLength={80}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') commit();
                  // Escape abandons the edit. Without it the only way out of a name you
                  // did not mean to start typing is to remember what it used to be.
                  if (event.key === 'Escape') setEditing(false);
                }}
              />
            ) : onRename ? (
              <WorkspaceName
                type="button"
                title={`${workspace.label} — click to rename`}
                onClick={() => {
                  setDraft(workspace.label);
                  setEditing(true);
                }}
              >
                {workspace.label}
              </WorkspaceName>
            ) : (
              <WorkspaceName as="span" title={workspace.label}>
                {workspace.label}
              </WorkspaceName>
            )}
            <WorkspaceMeta>
              {workspace.documentCount === 1
                ? '1 document'
                : `${workspace.documentCount} documents`}
            </WorkspaceMeta>
          </Workspace>
        </>
      )}

      <Spacer />

      <Tabs aria-label="Screens">
        {inWorkspace ? (
          <>
            {/*
              Scoped to this workspace. Pointing at "/" here would land a person on the
              first-run screen while the header still named their workspace, and dropping
              files there would silently fork a second one.
            */}
            <TabLink to={`/w/${workspace.id}/upload`} aria-current={current('upload')}>
              Upload
            </TabLink>
            <TabLink to={`/w/${workspace.id}/chat`} aria-current={current('chat')}>
              Chat
            </TabLink>
            <TabLink to={`/w/${workspace.id}/data`} aria-current={current('data')}>
              Data
            </TabLink>
          </>
        ) : (
          <>
            <TabLink to="/" aria-current={current('upload')}>
              Upload
            </TabLink>
            {/*
             * Not links, because there is nowhere to go: a workspace is created by the act
             * of uploading. Rendered as text rather than disabled buttons so they are
             * skipped by the keyboard rather than being focusable dead ends.
             */}
            <TabDisabled title="Add documents to start a conversation">Chat</TabDisabled>
            <TabDisabled title="Add documents to see the table">Data</TabDisabled>
          </>
        )}
      </Tabs>

      {/*
        After the screens, before the one action. The switch is a setting rather than a
        place to go, so it sits on the settings side of the segmented control, and putting
        it left of Add documents keeps the primary action hard against the right edge where
        it has been since the first screen.
      */}
      <AppearanceSwitch />

      {inWorkspace && onAddDocuments && (
        <AddButton type="button" onClick={onAddDocuments}>
          <Plus size={14} aria-hidden="true" />
          Add documents
        </AddButton>
      )}
    </Bar>
  );
}
