import { useMemo } from 'react';
import styled from 'styled-components';

import type { components } from '../../api/schema';

type RecordRow = components['schemas']['Record'];

/**
 * A count of how much of this table can be trusted.
 *
 * Computed in the browser, and that is deliberate rather than a shortcut. Product principle
 * 3 and decision D26 say displayed numbers must be computed by the server, never typed by
 * the model — the target of that rule is the **agent**, which plans aggregates and could
 * hallucinate a total. These five numbers are not planned by anything: they are a tally of
 * rows already on screen, by a tier the server derived. Counting them again on the server
 * would mean a round trip to be told what the client can already see, and a second place
 * for the definition of "needs review" to drift.
 *
 * The dashboard panels beside this are the opposite case, and they stay server-computed.
 */

const Card = styled.section`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
  padding: ${({ theme }) => theme.space.lg};

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.sm};
  box-shadow: ${({ theme }) => theme.shadow.card};
`;

const Title = styled.h3`
  font-family: ${({ theme }) => theme.font.display};
  font-weight: 400;
  font-size: 15px;
  color: ${({ theme }) => theme.color.ink};
`;

const Grid = styled.dl`
  margin: 0;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px 16px;
  font-size: 11px;

  dt {
    color: ${({ theme }) => theme.color.ink};
  }
  dd {
    margin: 0;
    text-align: right;
    font-family: ${({ theme }) => theme.font.mono};
    color: ${({ theme }) => theme.color.ink};
  }
`;

export function DocumentSummary({ records }: { records: RecordRow[] }) {
  const counts = useMemo(() => {
    let high = 0;
    let review = 0;
    let conflicts = 0;
    let unverified = 0;

    for (const record of records) {
      const values = Object.values(record.values ?? {});
      if (values.length === 0) {
        unverified += 1;
        continue;
      }

      // A document is described by its weakest cell, not its average: one low-confidence
      // total is what a person needs to look at, however clean the rest of the row is.
      const tiers = values.map((value) => value.tier);
      if (tiers.includes('conflict')) conflicts += 1;
      else if (tiers.includes('low') || tiers.includes('medium')) review += 1;
      else if (tiers.every((tier) => tier === 'high' || tier === 'verified')) high += 1;

      if (!values.some((value) => value.status === 'human_verified')) unverified += 1;
    }

    return { total: records.length, high, review, conflicts, unverified };
  }, [records]);

  return (
    <Card aria-label="Document summary">
      <Title>Document summary</Title>
      <Grid>
        <dt>Total documents</dt>
        <dd>{counts.total}</dd>
        <dt>High confidence</dt>
        <dd>{counts.high}</dd>
        <dt>Needs review</dt>
        <dd>{counts.review}</dd>
        <dt>Conflicts</dt>
        <dd>{counts.conflicts}</dd>
        <dt>Unverified</dt>
        <dd>{counts.unverified}</dd>
      </Grid>
    </Card>
  );
}
