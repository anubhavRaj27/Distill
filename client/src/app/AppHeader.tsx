import { Plus } from 'lucide-react';
import { Link } from 'react-router';
import styled from 'styled-components';

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

  background: ${({ theme }) => theme.color.paperRaised};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};
`;

const Divider = styled.div`
  flex-shrink: 0;
  width: 1px;
  height: 32px;
  background: ${({ theme }) => theme.color.line};
`;

const Workspace = styled.div`
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
`;

const WorkspaceName = styled.span`
  font-size: 14px;
  font-weight: 500;
  line-height: 1.25;
  color: ${({ theme }) => theme.color.ink};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
}

export function AppHeader({ workspace, active = 'upload', onAddDocuments }: AppHeaderProps) {
  const inWorkspace = workspace !== undefined;
  const current = (screen: Screen) => (active === screen ? ('page' as const) : undefined);

  return (
    <Bar>
      <Wordmark />

      {inWorkspace && (
        <>
          <Divider />
          <Workspace>
            <WorkspaceName title={workspace.label}>{workspace.label}</WorkspaceName>
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

      {inWorkspace && onAddDocuments && (
        <AddButton type="button" onClick={onAddDocuments}>
          <Plus size={14} aria-hidden="true" />
          Add documents
        </AddButton>
      )}
    </Bar>
  );
}
