import { describe, expect, it } from 'vitest';

import {
  emptyAnswer,
  parseAnswerEvent,
  reduceAnswer,
  stageLabel,
  type AnswerEvent,
  type Citation,
} from './answerStream';

/**
 * The fold from events to what the screen draws.
 *
 * Worth testing on its own because the interesting cases are all about *ordering and
 * repetition* — a resumed stream redelivering an event, a card arriving before prose — and
 * those are hard to provoke through the interface but trivial to state here.
 */

const citation = (n: number, excerpt: string): AnswerEvent => ({
  type: 'citation',
  n,
  chunk_id: `chunk-${n}`,
  document_id: 'doc-1',
  filename: 'contract_v2.pdf',
  page_index: 3,
  boxes: [],
  excerpt,
});

function fold(events: AnswerEvent[]) {
  return events.reduce(reduceAnswer, emptyAnswer('message-1'));
}

describe('parseAnswerEvent', () => {
  it('ignores a frame it does not recognise instead of failing the answer', () => {
    // A heartbeat, or an event type from a newer server. Neither is a reason to tear down
    // a half-written answer.
    expect(parseAnswerEvent({ event: 'ping', data: '' })).toBeNull();
    expect(parseAnswerEvent({ event: 'message', data: 'not json' })).toBeNull();
    expect(parseAnswerEvent({ event: 'x', data: '{"type":"nonsense"}' })).toBeNull();
  });

  it('trusts the type inside the payload, which is what the server derives the name from', () => {
    const event = parseAnswerEvent({
      event: 'message',
      data: '{"type":"token","text":"hi"}',
    });

    expect(event).toEqual({ type: 'token', text: 'hi' });
  });
});

describe('reduceAnswer', () => {
  it('accumulates tokens in order', () => {
    const state = fold([
      { type: 'token', text: 'Total spend is ' },
      { type: 'token', text: '$501,650.' },
    ]);

    expect(state.text).toBe('Total spend is $501,650.');
  });

  it('does not duplicate a citation the stream redelivers after a reconnect', () => {
    /*
     * `Last-Event-ID` resumes from the last frame the client *saw*, and a frame in flight
     * when the socket dropped was seen by nobody — so the server can legitimately replay
     * one the client already applied. Every other event here is idempotent by
     * construction; appending citations would not be.
     */
    const state = fold([
      citation(1, 'first delivery'),
      citation(2, 'another'),
      citation(1, 'redelivered after resume'),
    ]);

    expect(state.citations).toHaveLength(2);
    expect(state.citations.find((entry: Citation) => entry.n === 1)?.excerpt).toBe(
      'redelivered after resume',
    );
  });

  it('holds space for a visual until the server says whether there is one', () => {
    const fresh = emptyAnswer('message-1');
    expect(fresh.awaitingVisual).toBe(true);

    const skipped = reduceAnswer(fresh, {
      type: 'visual_skipped',
      reason: 'none_planned',
    });
    expect(skipped.awaitingVisual).toBe(false);
    expect(skipped.visual).toBeNull();
  });

  it('takes the finished message as authoritative', () => {
    const state = fold([
      { type: 'token', text: 'partial' },
      {
        type: 'done',
        message: {
          id: 'message-1',
          role: 'assistant',
          status: 'done',
          content: 'the whole answer',
        },
      },
    ]);

    expect(state.finished?.content).toBe('the whole answer');
    expect(state.stage).toBe('done');
  });

  it('keeps the correlation id with a failure, so a report is traceable', () => {
    const state = fold([
      { type: 'error', message: 'The model is unavailable.', correlation_id: 'req-42' },
    ]);

    expect(state.error).toContain('req-42');
    expect(state.stage).toBe('failed');
  });

  it('clears the reconnecting flag as soon as anything arrives', () => {
    const state = reduceAnswer(
      { ...emptyAnswer('message-1'), reconnecting: true },
      { type: 'token', text: 'back' },
    );

    expect(state.reconnecting).toBe(false);
  });
});

describe('stageLabel', () => {
  it('counts what was actually read once the sources arrive', () => {
    const state = fold([
      {
        type: 'sources',
        sources: [
          { chunk_id: 'a', document_id: 'd1', filename: 'one.pdf', page_index: 0, is_digest: false },
          { chunk_id: 'b', document_id: 'd1', filename: 'one.pdf', page_index: 1, is_digest: false },
          { chunk_id: 'c', document_id: 'd2', filename: 'two.pdf', page_index: 0, is_digest: false },
        ],
      },
      { type: 'status', stage: 'reading' },
    ]);

    // Passages and documents are different counts, and conflating them would overstate
    // how much of the corpus the answer touched.
    expect(stageLabel(state)).toBe('Read 3 passages from 2 documents');
  });

  it('says it is reconnecting rather than freezing on the last stage', () => {
    const state = { ...emptyAnswer('m'), stage: 'answering' as const, reconnecting: true };
    expect(stageLabel(state)).toBe('Reconnecting…');
  });
});
