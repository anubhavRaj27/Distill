import { useCallback, useState } from 'react';
import styled from 'styled-components';

import { sortIntake, type RejectedFile } from '../../lib/files';
import { logger } from '../../lib/logger';
import { ParticleText } from '../../ui/ParticleText';
import { theme } from '../../ui/theme';
import { DropZone } from './components/DropZone';
import { RejectionNotice } from './components/RejectionNotice';
import { useStartWorkspace } from './useStartWorkspace';

/**
 * Screen 1 of three: Upload. Route `/`. Requirements section 3.1.
 *
 * A person who has never seen this product should understand it and be able to start in one
 * action. Everything here earns its place against that: the name, one sentence saying what
 * happens, a place to put files, and a way in with no files of your own. Dropping files or
 * asking for the samples creates the workspace and hands off, where the processing strip
 * takes over — this screen never becomes a progress page.
 *
 * Deliberately absent: a feature grid, a sign-up, a tour. There are no accounts (decision
 * D8), so nothing stands between arriving and starting. Also absent, since September 5:
 * the application header, and the funnel illustration that used to sit below the fold.
 * Decision D57 records why.
 */

const Page = styled.div`
  min-height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: ${({ theme }) => theme.space.page} ${({ theme }) => theme.space.xl};
  background: ${({ theme }) => theme.color.paper};
`;

const Main = styled.main`
  width: 100%;
  max-width: ${({ theme }) => theme.measure.prose};
  display: flex;
  flex-direction: column;
  align-items: center;
`;

/**
 * The name, drawn as particles that scatter under the cursor and settle back.
 *
 * It is the same argument the funnel illustration used to make — a scattered pile
 * resolving into something exact — made once, at the top, in the product's own name,
 * instead of in a 274px diagram that pushed the drop zone toward the fold.
 */
const Title = styled.h1`
  width: 100%;
  margin: 0;
`;

const Standfirst = styled.p`
  margin-top: ${({ theme }) => theme.space.xs};
  max-width: ${({ theme }) => theme.measure.narrow};
  font-size: 15px;
  line-height: 1.7;
  text-align: center;
  text-wrap: pretty;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Intake = styled.div`
  margin-top: ${({ theme }) => theme.space.xxl};
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

/** What the drop zone will and will not take, stated before anyone tries. Requirement FR-03. */
const Formats = styled.p`
  margin-top: ${({ theme }) => theme.space.xxl};
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: ${({ theme }) => theme.color.inkMuted};
  opacity: 0.75;
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
      if (refused.length > 0) {
        logger.event('files.rejected', {
          count: refused.length,
          reasons: refused.map((entry) => entry.reason),
        });
      }

      if (accepted.length > 0) {
        // The refusals travel with the batch: this screen is about to be replaced, and a
        // notice rendered here would vanish in the same tick it appeared.
        start.mutate({ kind: 'files', files: accepted, rejected: refused });
        return;
      }

      // Nothing acceptable, so nobody is going anywhere. Report it right here.
      setRejected(refused);
    },
    [start],
  );

  const handleSamples = useCallback(() => {
    setRejected([]);
    start.mutate({ kind: 'samples' });
  }, [start]);

  return (
    <Page>
      <Main>
        <Title>
          <ParticleText
            text="Distill"
            fontFamily={theme.font.display}
            fontSize={176}
            height={210}
            particleDensity={3}
            particleSize={1.5}
          />
        </Title>

        <Standfirst>
          Drop in a pile of documents. We read them and pull out what matters, into one
          table you can search, question, and trace back to the page it came from.
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

        <Formats>PDF · DOCX · XLSX · CSV · Images · Text</Formats>
      </Main>
    </Page>
  );
}
