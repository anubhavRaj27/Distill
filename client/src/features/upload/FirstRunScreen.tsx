import { useCallback, useState } from 'react';
import styled from 'styled-components';

import { AppHeader } from '../../app/AppHeader';
import { sortIntake, type RejectedFile } from '../../lib/files';
import { logger } from '../../lib/logger';
import { DistillationMark } from './components/DistillationMark';
import { DropZone } from './components/DropZone';
import { RejectionNotice } from './components/RejectionNotice';
import { useStartWorkspace } from './useStartWorkspace';

/**
 * Screen 1 of three: Upload. Route `/`. Requirements section 3.1.
 *
 * A person who has never seen this product should understand it and be able to start in one
 * action. Everything here earns its place against that: what to do, what is accepted, a
 * place to put files, and a way in with no files of your own. Dropping files or asking for
 * the samples creates the workspace and hands off to Chat, where the processing strip takes
 * over — this screen never becomes a progress page.
 *
 * Deliberately absent: a feature grid, a sign-up, a tour. There are no accounts (decision
 * D8), so nothing stands between arriving and starting.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

const Main = styled.main`
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: ${({ theme }) => theme.space.page};
`;

const Intro = styled.section`
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: ${({ theme }) => theme.space.lg};
  text-align: center;
  width: 100%;
`;

const Headline = styled.h1`
  font-family: ${({ theme }) => theme.font.display};
  font-weight: 400;
  font-size: 34px;
  line-height: 1.15;
  color: ${({ theme }) => theme.color.ink};
  text-wrap: balance;
`;

const Standfirst = styled.p`
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 14px;
  line-height: 1.7;
  color: ${({ theme }) => theme.color.inkMuted};
  text-wrap: pretty;
`;

const Intake = styled.div`
  margin-top: ${({ theme }) => theme.space.lg};
  width: 640px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
`;

/**
 * The sample path, requirement FR-05.
 *
 * Quieter than "Choose files" but immediately below it, because for a first-time visitor
 * with nothing to hand it is the more useful of the two. It is a real button, not a link:
 * it performs an action rather than navigating.
 */
const SampleAction = styled.button`
  appearance: none;
  margin-top: ${({ theme }) => theme.space.lg};
  padding: 4px 8px;

  font-family: inherit;
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
  background: none;
  border: 0;
  cursor: pointer;
  transition: color ${({ theme }) => theme.motion.quick};

  span {
    color: ${({ theme }) => theme.color.ink};
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  &:hover:not(:disabled) {
    color: ${({ theme }) => theme.color.ink};
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
`;

const StartError = styled.p`
  margin-top: ${({ theme }) => theme.space.lg};
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 13px;
  text-align: center;
  color: ${({ theme }) => theme.tier.conflict.color};

  code {
    font-family: ${({ theme }) => theme.font.mono};
    font-size: 12px;
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

const Illustration = styled.section`
  margin-top: ${({ theme }) => theme.space.section};
  display: flex;
  justify-content: center;
  width: 100%;
`;

export function FirstRunScreen() {
  const [rejected, setRejected] = useState<RejectedFile[]>([]);
  const start = useStartWorkspace();
  const busy = start.isPending;

  const handleFiles = useCallback(
    (files: File[]) => {
      const { accepted, rejected: refused } = sortIntake(files);

      // Requirement FR-03: refusals are shown inline and immediately, before any bytes
      // leave the browser. A mixed selection still uploads what it can — refusing a whole
      // batch over one bad file would be the wrong trade for someone dropping a folder.
      setRejected(refused);
      if (refused.length > 0) {
        logger.event('files.rejected', {
          count: refused.length,
          reasons: refused.map((entry) => entry.reason),
        });
      }

      if (accepted.length > 0) start.mutate({ kind: 'files', files: accepted });
    },
    [start],
  );

  const handleSamples = useCallback(() => {
    setRejected([]);
    start.mutate({ kind: 'samples' });
  }, [start]);

  return (
    <Page>
      <AppHeader />

      <Main>
        <Intro>
          <Headline>Drop your documents in.</Headline>
          <Standfirst>
            PDF, DOCX, XLSX, CSV, images, and plain text. We read the pile and pull out what
            matters.
          </Standfirst>

          <Intake aria-busy={busy}>
            <DropZone onFiles={handleFiles} disabled={busy} />

            {rejected.length > 0 && <RejectionNotice rejected={rejected} />}

            {start.isError ? (
              <StartError role="alert">
                {start.error.message}
                {start.error.correlationId && (
                  <>
                    {' '}
                    <code>{start.error.correlationId}</code>
                  </>
                )}
              </StartError>
            ) : (
              <SampleAction type="button" disabled={busy} onClick={handleSamples}>
                {busy && start.variables?.kind === 'samples' ? (
                  'Loading sample documents…'
                ) : (
                  <>
                    No documents to hand? <span>Try with sample documents</span>
                  </>
                )}
              </SampleAction>
            )}
          </Intake>
        </Intro>

        <Illustration aria-label="Documents settling into a structured table">
          <DistillationMark />
        </Illustration>
      </Main>
    </Page>
  );
}
