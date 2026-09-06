import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api, authHeader, toFailure, type ApiFailure } from '../../api/client';
import { logger } from '../../lib/logger';
import { consumeSse } from '../../lib/sse';
import {
  emptyAnswer,
  parseAnswerEvent,
  reduceAnswer,
  type ChatMessage,
  type LiveAnswer,
} from './answerStream';

/**
 * The conversation: history, asking, following the answer, and stopping it.
 *
 * Two sources of truth, kept deliberately separate rather than merged into one list:
 *
 * - **History** is what the server has persisted, cached by React Query. A message here
 *   that says `streaming` has empty content on purpose — the text lives in the server's
 *   buffer until the answer finishes.
 * - **The live answer** is the one being written right now, folded from stream events by
 *   `reduceAnswer`. It is local state, not cache, because it changes on every token and
 *   writing that through a query cache would invalidate and re-render the whole list
 *   hundreds of times per answer.
 *
 * They meet exactly once, at `done`: the event carries the persisted message, which
 * replaces the live one in the cache wholesale. The server calls that payload
 * authoritative and it is treated as such, which is what makes a late or reconnected
 * client converge on the same state as one that watched the whole thing.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? '';

export interface Conversation {
  messages: ChatMessage[];
  live: LiveAnswer | null;
  /** The question just asked, shown before the server echoes it back. */
  isLoading: boolean;
  error: ApiFailure | null;
  ask: (question: string) => void;
  isAsking: boolean;
  stop: () => void;
  canStop: boolean;
}

export function useConversation(workspaceId: string, token: string | null): Conversation {
  const queryClient = useQueryClient();
  const queryKey = ['chat', workspaceId] as const;

  const history = useQuery({
    queryKey,
    enabled: Boolean(token),
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        '/api/v1/workspaces/{workspace_id}/chat/messages',
        {
          params: {
            path: { workspace_id: workspaceId },
            header: authHeader(token!),
          },
        },
      );
      if (error || !data) throw toFailure(error, response?.status);
      return data.messages;
    },
  });

  const [live, setLive] = useState<LiveAnswer | null>(null);
  const stream = useRef<AbortController | null>(null);

  /** Merge a finished message into the cache, replacing any earlier copy of it. */
  const absorb = useCallback(
    (message: ChatMessage) => {
      queryClient.setQueryData<ChatMessage[]>(queryKey, (current = []) => {
        const index = current.findIndex((entry) => entry.id === message.id);
        if (index === -1) return [...current, message];
        return current.map((entry, at) => (at === index ? message : entry));
      });
    },
    // `queryKey` is a fresh array each render; its contents are what matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, workspaceId],
  );

  /**
   * Open the answer stream and fold it into `live` until it ends.
   *
   * `url` is taken from the ask response rather than built here, because the server hands
   * it over precisely so the route can move without breaking the client. The one place it
   * IS constructed is reattachment below, where there is no ask response to read it from.
   */
  const follow = useCallback(
    (messageId: string, url: string) => {
      if (!token) return;

      stream.current?.abort();
      const controller = new AbortController();
      stream.current = controller;
      setLive(emptyAnswer(messageId));

      void consumeSse({
        url: `${BASE_URL}${url}`,
        headers: authHeader(token),
        signal: controller.signal,
        onReconnect: (attempt) => {
          logger.event('chat.stream_reconnect', { messageId, attempt });
          setLive((current) =>
            current && current.messageId === messageId
              ? { ...current, reconnecting: true }
              : current,
          );
        },
        onMessage: (frame) => {
          const event = parseAnswerEvent(frame);
          if (!event) return;

          if (event.type === 'done') {
            absorb(event.message);
            // The persisted message is now in the list, so the live copy would render the
            // same answer twice for one frame if it lingered.
            setLive((current) =>
              current && current.messageId === messageId ? null : current,
            );
            return;
          }

          setLive((current) =>
            current && current.messageId === messageId
              ? reduceAnswer(current, event)
              : current,
          );
        },
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return;

        /*
         * The stream gave up rather than finishing. The answer itself may well have
         * completed on the server — generation does not depend on anyone listening
         * (decision D32) — so the history is refetched rather than the message being
         * written off, and the live copy reports what went wrong until it arrives.
         */
        logger.event('chat.stream_failed', {
          messageId,
          detail: error instanceof Error ? error.message : String(error),
        });
        setLive((current) =>
          current && current.messageId === messageId
            ? {
                ...current,
                stage: 'failed',
                reconnecting: false,
                error:
                  'Lost the connection to the answer. It may still have finished — reload to see.',
              }
            : current,
        );
        void queryClient.invalidateQueries({ queryKey });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [absorb, queryClient, token, workspaceId],
  );

  const askMutation = useMutation<
    { messageId: string; streamUrl: string },
    ApiFailure,
    string
  >({
    mutationFn: async (question) => {
      const { data, error, response } = await api.POST(
        '/api/v1/workspaces/{workspace_id}/chat/messages',
        {
          params: {
            path: { workspace_id: workspaceId },
            header: authHeader(token!),
          },
          body: { question },
        },
      );
      if (error || !data) throw toFailure(error, response?.status);

      // The user's own message is persisted by the same request, so it goes into the list
      // immediately rather than waiting for a refetch that would make it appear late.
      absorb(data.user_message);
      return { messageId: data.message_id, streamUrl: data.stream_url };
    },
    onSuccess: ({ messageId, streamUrl }) => follow(messageId, streamUrl),
  });

  const stopMutation = useMutation<void, ApiFailure, string>({
    mutationFn: async (messageId) => {
      const { error, response } = await api.POST(
        '/api/v1/workspaces/{workspace_id}/chat/messages/{message_id}/stop',
        {
          params: {
            path: { workspace_id: workspaceId, message_id: messageId },
            header: authHeader(token!),
          },
        },
      );
      if (error) throw toFailure(error, response?.status);
      /*
       * The stream is not aborted here. Stopping settles the message on the server, which
       * publishes `status: stopped` and then `done` on the same buffer — so the partial
       * answer arrives through the normal path and is kept, which is what the route
       * promises. Tearing down the socket would drop that final state on the floor.
       */
    },
  });

  /**
   * Reattach to an answer that was still being written when this client last looked.
   *
   * The case is a refresh mid-answer, or a shared link opened while someone else's
   * question is generating. The server keeps writing regardless of who is listening
   * (decision D32), so the persisted row says `streaming` and the buffer is still there to
   * be tailed. Without this the message would sit blank forever.
   */
  const reattached = useRef<string | null>(null);
  useEffect(() => {
    if (!token || live !== null) return;

    const pending = (history.data ?? []).find(
      (message) => message.role === 'assistant' && message.status === 'streaming',
    );
    if (!pending || reattached.current === pending.id) return;

    reattached.current = pending.id;
    logger.event('chat.stream_reattach', { messageId: pending.id });
    follow(
      pending.id,
      `/api/v1/workspaces/${workspaceId}/chat/messages/${pending.id}/stream`,
    );
  }, [follow, history.data, live, token, workspaceId]);

  // One stream at a time, and none once the screen is gone.
  useEffect(() => () => stream.current?.abort(), []);

  const messages = history.data ?? [];

  return {
    messages,
    live,
    isLoading: history.isPending && Boolean(token),
    error: history.isError ? history.error : (askMutation.error ?? null),
    ask: (question: string) => askMutation.mutate(question),
    isAsking: askMutation.isPending,
    stop: () => {
      if (live) stopMutation.mutate(live.messageId);
    },
    // Only while there is something to stop: a live answer that has not already settled.
    canStop:
      live !== null &&
      live.finished === null &&
      live.stage !== 'failed' &&
      !stopMutation.isPending,
  };
}
