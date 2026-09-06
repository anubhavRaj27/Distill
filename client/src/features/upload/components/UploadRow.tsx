import { AlertCircle, CheckCircle2, FileText } from 'lucide-react';
import styled from 'styled-components';

import { formatBytes } from '../../../lib/files';
import type { UploadTask } from '../../../lib/upload';
import { stageWord } from '../../processing/stageWords';
import type { DocumentProgress } from '../../processing/useDocumentProgress';

/**
 * One file, from the browser's disk to a document that can be asked about.
 *
 * The row used to stop at "Ready", meaning the server had the bytes — which is a strange
 * place for a progress row to stop, since nothing useful has happened yet at that point.
 * It now carries on through what the server does with the file: reading it, pulling out
 * values, making it searchable. "Ready" is the end of the whole pipeline, not the end of
 * the transfer (decision D76).
 *
 * State is carried on three channels at once, never colour alone: the bar's fill, a word,
 * and an icon. That is the same rule the confidence tiers follow, applied here because this
 * row is the first thing a person watches and the first place they could be misled.
 */

const Row = styled.li`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.lg};
  padding: ${({ theme }) => theme.space.xl};
  border-bottom: 1px solid ${({ theme }) => theme.color.line};

  &:last-child {
    border-bottom: 0;
  }
`;

const Thumb = styled.div`
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;

  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paper};
  border-radius: ${({ theme }) => theme.radius.md};
`;

const Middle = styled.div`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.sm};
`;

const Filename = styled.span`
  font-size: 16px;
  color: ${({ theme }) => theme.color.ink};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

/**
 * A native `<progress>` rather than a pair of divs: it is announced by screen readers, it
 * carries its own value semantics, and `indeterminate` is expressible by omitting `value`.
 */
const Bar = styled.progress`
  appearance: none;
  display: block;
  width: 100%;
  height: 4px;
  border: 0;
  border-radius: ${({ theme }) => theme.radius.pill};

  &::-webkit-progress-bar {
    background: ${({ theme }) => theme.color.line};
    border-radius: ${({ theme }) => theme.radius.pill};
  }
  &::-webkit-progress-value {
    background: ${({ theme }) => theme.color.ink};
    border-radius: ${({ theme }) => theme.radius.pill};
    transition: inline-size ${({ theme }) => theme.motion.quick};
  }
  &::-moz-progress-bar {
    background: ${({ theme }) => theme.color.ink};
    border-radius: ${({ theme }) => theme.radius.pill};
  }

  &[data-failed='true'] {
    &::-webkit-progress-value {
      background: ${({ theme }) => theme.tier.conflict.color};
    }
    &::-moz-progress-bar {
      background: ${({ theme }) => theme.tier.conflict.color};
    }
  }
`;

const Right = styled.div`
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.md};
`;

const Meta = styled.div`
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
  text-align: right;
`;

const Status = styled.span`
  &[data-failed='true'] {
    color: ${({ theme }) => theme.tier.conflict.color};
  }
`;

const Mark = styled.span`
  display: flex;
  align-items: center;
  color: ${({ theme }) => theme.tier.verified.color};

  &[data-failed='true'] {
    color: ${({ theme }) => theme.tier.conflict.color};
  }
`;

/** The server's own sentence about this stage: "scanned image detected", "2 passages indexed". */
const Detail = styled.p`
  font-size: 12px;
  line-height: 1.45;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Reason = styled.p`
  font-size: 12px;
  line-height: 1.45;
  color: ${({ theme }) => theme.tier.conflict.color};
`;

/** What this file's own document is doing on the server, once it has one. */
export interface RowStage {
  status: DocumentProgress['status'];
  detail?: string | null;
  failureReason?: string | null;
}

function statusLabel(task: UploadTask, stage?: RowStage): string {
  if (task.phase === 'failed') return 'Could not send';

  /*
   * Once the bytes are in, the server's word wins. A file sitting at "Ready" while the
   * server is still reading it is the row claiming the job is done when it has barely
   * started.
   */
  if (task.phase === 'ready' && stage) {
    if (stage.status === 'failed') return 'Could not be read';
    if (stage.status === 'done') return 'Ready';
    return stageWord(stage.status);
  }

  switch (task.phase) {
    case 'waiting':
      return 'Queued';
    case 'sending':
      return 'Sending';
    case 'ready':
      // Arrived, and nothing has been heard from the server about it yet.
      return 'Sent';
  }
}

export function UploadRow({ task, stage }: { task: UploadTask; stage?: RowStage }) {
  const sendFailed = task.phase === 'failed';
  const readFailed = stage?.status === 'failed';
  const failed = sendFailed || readFailed;
  const settled = stage?.status === 'done';
  const total = task.file.size;
  const label = statusLabel(task, stage);
  const reason = sendFailed ? task.error : readFailed ? stage?.failureReason : null;

  return (
    <Row>
      <Thumb aria-hidden="true">
        <FileText size={18} />
      </Thumb>

      <Middle>
        <Filename title={task.file.name}>{task.file.name}</Filename>
        <Bar
          data-failed={failed}
          /*
           * Three cases, and the indeterminate one matters. A queued file has no fraction
           * yet and a failed one should not pretend to a position, so `value` is omitted
           * and the bar renders indeterminate — which is also exactly right while the
           * server is reading the file, where there are stages but no measurable fraction.
           */
          {...(settled
            ? { value: 1, max: 1 }
            : task.phase === 'sending' || (task.phase === 'ready' && !stage)
              ? { value: task.sent, max: Math.max(total, 1) }
              : {})}
          aria-label={`${task.file.name}: ${label}`}
        />
        {failed && reason && <Reason>{reason}</Reason>}
        {!failed && stage?.detail && <Detail>{stage.detail}</Detail>}
      </Middle>

      <Right>
        <Meta>
          <span>{formatBytes(total)}</span>
          <Status data-failed={failed}>{label}</Status>
        </Meta>
        <Mark data-failed={failed} aria-hidden="true">
          {failed ? <AlertCircle size={20} /> : settled ? <CheckCircle2 size={20} /> : null}
        </Mark>
      </Right>
    </Row>
  );
}
