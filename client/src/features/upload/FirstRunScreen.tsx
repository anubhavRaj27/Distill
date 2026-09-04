import { useCallback, useRef, useState } from 'react';
import styled from 'styled-components';

import { Button } from '../../ui/Button';
import { Wordmark } from '../../ui/Wordmark';
import { sortIntake, type RejectedFile } from '../../lib/files';
import { logger } from '../../lib/logger';
import { DistillationMark } from './components/DistillationMark';
import { DropZone } from './components/DropZone';
import { RejectionNotice } from './components/RejectionNotice';
import { useStartWorkspace } from './useStartWorkspace';

/**
 * Screen 1: first run, no workspace yet.
 *
 * This screen is the trust pitch. A person who has never seen the product should
 * understand it in about thirty seconds without reading documentation, and should be able
 * to try it in one click (product principle 5, requirement FR-05). Everything on it earns
 * its place against that: one sentence of what happens, one picture of mess becoming a
 * table, one place to put files, two ways to start.
 *
 * Deliberately absent: a feature grid, a sign-up, a tour. There are no accounts in this
 * product (decision D8), so there is nothing to stand between arriving and starting.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.color.paper};
`;

const Masthead = styled.header`
  padding: ${({ theme }) => theme.space.xxl} ${({ theme }) => theme.space.page}
    0;
`;

const Main = styled.main`
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: ${({ theme }) => theme.space.section} ${({ theme }) => theme.space.page};
`;

const Hero = styled.div`
  width: 100%;
  max-width: ${({ theme }) => theme.measure.prose};
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: ${({ theme }) => theme.space.lg};
`;

const Headline = styled.h1`
  font-family: ${({ theme }) => theme.font.display};
  font-weight: 400;
  font-size: clamp(28px, 4vw, 40px);
  line-height: 1.15;
  letter-spacing: -0.01em;
  color: ${({ theme }) => theme.color.ink};
  text-wrap: balance;
`;

const Standfirst = styled.p`
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 16px;
  line-height: 1.5;
  color: ${({ theme }) => theme.color.inkMuted};
  text-wrap: pretty;
`;

const Illustration = styled.div`
  margin-top: ${({ theme }) => theme.space.xxl};
  display: flex;
  justify-content: center;
  width: 100%;
`;

const Intake = styled.section`
  margin-top: ${({ theme }) => theme.space.xxl};
  width: 100%;
  max-width: ${({ theme }) => theme.measure.prose};
  display: flex;
  flex-direction: column;
  align-items: center;
`;

const Actions = styled.div`
  margin-top: ${({ theme }) => theme.space.xl};
  display: flex;
  justify-content: center;
  align-items: center;
  gap: ${({ theme }) => theme.space.lg};
  flex-wrap: wrap;

  /*
   * Both routes in are the same width and sit side by side. "Try with sample documents"
   * is not a lesser option: for a first-time visitor it is usually the better one, and the
   * requirements ask for it to be equally prominent.
   */
  > button {
    width: 220px;
  }
`;

const Footnote = styled.p`
  margin-top: ${({ theme }) => theme.space.lg};
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const StartError = styled.p`
  margin-top: ${({ theme }) => theme.space.lg};
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 14px;
  text-align: center;
  color: ${({ theme }) => theme.tier.conflict.color};

  code {
    font-family: ${({ theme }) => theme.font.mono};
    font-size: 12px;
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

const Colophon = styled.footer`
  border-top: 1px solid ${({ theme }) => theme.color.line};
  margin-top: ${({ theme }) => theme.space.section};
  padding: ${({ theme }) => theme.space.lg} ${({ theme }) => theme.space.page};

  p {
    text-align: center;
    font-size: 12px;
    color: ${({ theme }) => theme.color.inkMuted};
  }
`;

export function FirstRunScreen() {
  const [rejected, setRejected] = useState<RejectedFile[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const start = useStartWorkspace();
  const busy = start.isPending;

  const handleFiles = useCallback(
    (files: File[]) => {
      const { accepted, rejected: refused } = sortIntake(files);

      // Requirement FR-03: refusals are shown inline and immediately, before any bytes
      // leave the browser. A mixed selection still uploads what it can — refusing the
      // whole batch over one bad file would be the wrong trade for someone dropping a
      // folder.
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
      <Masthead>
        <Wordmark />
      </Masthead>

      <Main>
        <Hero>
          <Headline>Every invoice, receipt, and statement — one table you can trust.</Headline>
          <Standfirst>
            Drop in whatever you have. Distill reads it, reconciles it against everything
            else, and shows you exactly where every number came from.
          </Standfirst>
        </Hero>

        <Illustration>
          <DistillationMark />
        </Illustration>

        <Intake aria-busy={busy}>
          <DropZone onFiles={handleFiles} disabled={busy} inputRef={fileInput} />

          {rejected.length > 0 && <RejectionNotice rejected={rejected} />}

          <Actions>
            <Button
              type="button"
              $variant="primary"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              {busy && start.variables?.kind === 'files' ? 'Starting…' : 'Choose files'}
            </Button>
            <Button type="button" $variant="secondary" disabled={busy} onClick={handleSamples}>
              {busy && start.variables?.kind === 'samples'
                ? 'Loading samples…'
                : 'Try with sample documents'}
            </Button>
          </Actions>

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
            <Footnote>No account needed to try it — sample data only.</Footnote>
          )}
        </Intake>
      </Main>

      <Colophon>
        <p>Distill · your documents never leave this workspace without your say</p>
      </Colophon>
    </Page>
  );
}
