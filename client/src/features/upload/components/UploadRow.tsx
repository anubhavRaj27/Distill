import { AlertCircle, CheckCircle2, FileText } from 'lucide-react';
import styled from 'styled-components';

import { formatBytes } from '../../../lib/files';
import type { UploadTask } from '../../../lib/upload';

/**
 * One file on its way to the server.
 *
 * State is carried on three channels at once, never colour alone: the bar's fill, a word
 * ("Sending", "Ready", "Could not send"), and an icon. That is the same rule the confidence
 * tiers follow, applied here because this row is the first thing a person watches and the
 * first place they could be misled.
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

const Reason = styled.p`
  font-size: 12px;
  line-height: 1.45;
  color: ${({ theme }) => theme.tier.conflict.color};
`;

function statusLabel(task: UploadTask): string {
  switch (task.phase) {
    case 'waiting':
      return 'Queued';
    case 'sending':
      return 'Sending';
    case 'ready':
      return 'Ready';
    case 'failed':
      return 'Could not send';
  }
}

export function UploadRow({ task }: { task: UploadTask }) {
  const failed = task.phase === 'failed';
  const total = task.file.size;
  const label = statusLabel(task);

  return (
    <Row>
      <Thumb aria-hidden="true">
        <FileText size={18} />
      </Thumb>

      <Middle>
        <Filename title={task.file.name}>{task.file.name}</Filename>
        <Bar
          data-failed={failed}
          // A queued file has no meaningful fraction yet, and a failed one should not
          // pretend to a position. Omitting `value` renders the indeterminate state.
          {...(task.phase === 'sending' || task.phase === 'ready'
            ? { value: task.sent, max: Math.max(total, 1) }
            : {})}
          aria-label={`${task.file.name}: ${label}`}
        />
        {failed && task.error && <Reason>{task.error}</Reason>}
      </Middle>

      <Right>
        <Meta>
          <span>{formatBytes(total)}</span>
          <Status data-failed={failed}>{label}</Status>
        </Meta>
        <Mark data-failed={failed} aria-hidden="true">
          {failed ? <AlertCircle size={20} /> : task.phase === 'ready' ? (
            <CheckCircle2 size={20} />
          ) : null}
        </Mark>
      </Right>
    </Row>
  );
}
