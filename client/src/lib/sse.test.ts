import { afterEach, describe, expect, it, vi } from 'vitest';

import { consumeSse, parseChunk, SseError, type SseMessage } from './sse';

/**
 * The transport, tested where it is actually hard.
 *
 * Two things break real SSE clients and neither is visible in a happy-path test: a frame
 * split across network chunks, and a reconnect that fails to resume. Both are covered
 * here, because both produce *plausible-looking* output when broken — a dropped token, a
 * repeated paragraph — rather than an error anyone would notice.
 */

/** A response whose body arrives in the given pieces, as a real stream would. */
function streamed(pieces: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseChunk', () => {
  it('reads id, event and data out of one frame', () => {
    const { messages, rest } = parseChunk('id: 7\nevent: token\ndata: {"a":1}\n\n');

    expect(messages).toEqual([{ id: '7', event: 'token', data: '{"a":1}' }]);
    expect(rest).toBe('');
  });

  it('holds back a frame that has not finished arriving', () => {
    const { messages, rest } = parseChunk('event: token\ndata: {"tex');

    // Dispatching this would hand JSON.parse a truncated object.
    expect(messages).toEqual([]);
    expect(rest).toBe('event: token\ndata: {"tex');
  });

  it('joins multi-line data with newlines, as the specification requires', () => {
    const { messages } = parseChunk('data: first\ndata: second\n\n');

    expect(messages[0]!.data).toBe('first\nsecond');
  });

  it('drops comments, which is what a keep-alive is', () => {
    // `sse-starlette` sends its heartbeat as a comment every fifteen seconds.
    const { messages } = parseChunk(': ping - 2026-09-05\n\ndata: real\n\n');

    expect(messages).toHaveLength(1);
    expect(messages[0]!.data).toBe('real');
  });

  it('names an unnamed event "message"', () => {
    const { messages } = parseChunk('data: bare\n\n');

    expect(messages[0]!.event).toBe('message');
  });
});

describe('consumeSse', () => {
  it('reassembles a frame split across chunk boundaries', async () => {
    // The split falls mid-JSON, which is exactly where a real one falls during a token
    // stream: the server flushes per token and the network coalesces however it likes.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamed(['event: token\ndata: {"type":"tok', 'en","text":"hello"}\n\n']),
      ),
    );

    const seen: SseMessage[] = [];
    await consumeSse({
      url: '/stream',
      signal: new AbortController().signal,
      onMessage: (message) => seen.push(message),
    });

    expect(seen).toHaveLength(1);
    expect(JSON.parse(seen[0]!.data)).toEqual({ type: 'token', text: 'hello' });
  });

  it('resumes from the last event it saw when the connection drops', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('network error'))
      .mockResolvedValueOnce(streamed(['id: 5\ndata: resumed\n\n']));
    vi.stubGlobal('fetch', fetchMock);

    const seen: SseMessage[] = [];
    const reconnects: number[] = [];
    await consumeSse({
      url: '/stream',
      signal: new AbortController().signal,
      lastEventId: '4',
      onMessage: (message) => seen.push(message),
      onReconnect: (attempt) => reconnects.push(attempt),
    });

    expect(reconnects).toEqual([1]);
    expect(seen.map((message) => message.data)).toEqual(['resumed']);

    // Requirement FR-29: the retry says where it got to, so the server replays the gap
    // rather than the whole answer.
    const retry = fetchMock.mock.calls[1]![1] as RequestInit;
    expect((retry.headers as Record<string, string>)['Last-Event-ID']).toBe('4');
  });

  it('carries the last id forward from the events it did receive', async () => {
    /*
     * A socket that drops mid-answer: two frames are delivered, then the read fails. The
     * error is raised from `pull` rather than `start`, because `controller.error()` in
     * `start` discards everything already queued — which would test a connection that
     * delivered nothing, not one that delivered two frames and then died.
     */
    const dropsAfterTwoFrames = () => {
      const encoder = new TextEncoder();
      let delivered = false;
      return new Response(
        new ReadableStream<Uint8Array>({
          pull(controller) {
            if (!delivered) {
              delivered = true;
              controller.enqueue(
                encoder.encode('id: 11\ndata: a\n\nid: 12\ndata: b\n\n'),
              );
              return;
            }
            controller.error(new TypeError('connection reset'));
          },
        }),
        { status: 200 },
      );
    };

    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => dropsAfterTwoFrames())
      .mockResolvedValueOnce(streamed(['id: 13\ndata: c\n\n']));
    vi.stubGlobal('fetch', fetchMock);

    const seen: string[] = [];
    await consumeSse({
      url: '/stream',
      signal: new AbortController().signal,
      onMessage: (message) => seen.push(message.data),
    });

    expect(seen).toEqual(['a', 'b', 'c']);
    const retry = fetchMock.mock.calls[1]![1] as RequestInit;
    expect((retry.headers as Record<string, string>)['Last-Event-ID']).toBe('12');
  });

  it('does not retry a refusal the server meant', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('nope', { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      consumeSse({
        url: '/stream',
        signal: new AbortController().signal,
        onMessage: () => {},
      }),
    ).rejects.toBeInstanceOf(SseError);

    // Retrying an expired token just repeats the same refusal on a timer.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('gives up after the retry budget rather than hammering a dead server', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network error'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      consumeSse({
        url: '/stream',
        signal: new AbortController().signal,
        onMessage: () => {},
        maxRetries: 2,
      }),
    ).rejects.toThrow(/network error/);

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('stops immediately when aborted', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => {
        controller.abort();
        return Promise.reject(new DOMException('aborted', 'AbortError'));
      }),
    );

    await expect(
      consumeSse({ url: '/stream', signal: controller.signal, onMessage: () => {} }),
    ).rejects.toBeDefined();
  });
});
