import styled from 'styled-components';

import { formatBytes, type RejectedFile } from '../../../lib/files';

/**
 * Files that were refused before upload. Requirement FR-03.
 *
 * The design brief for every error state in this product: calm, specific, and never a raw
 * dump. So each row names the file, says what is wrong with it in a sentence, and says
 * what would have worked. It sits inline beneath the drop zone rather than in a toast,
 * because a person who dropped twelve files needs to read this list at their own pace.
 *
 * The tier palette carries the warning colour, but the heading and the per-file sentences
 * carry the meaning on their own. Nothing here depends on seeing a colour.
 */

const Notice = styled.div`
  width: 100%;
  margin-top: ${({ theme }) => theme.space.lg};
  padding: ${({ theme }) => theme.space.lg};

  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-left: 3px solid ${({ theme }) => theme.tier.low.color};
  border-radius: ${({ theme }) => theme.radius.sm};
  text-align: left;
`;

const Heading = styled.h2`
  font-size: 14px;
  font-weight: 600;
  color: ${({ theme }) => theme.color.ink};
  margin-bottom: ${({ theme }) => theme.space.sm};
`;

const List = styled.ul`
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.sm};
`;

const Item = styled.li`
  font-size: 13px;
  line-height: 1.45;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Filename = styled.span`
  font-family: ${({ theme }) => theme.font.mono};
  font-size: 12px;
  color: ${({ theme }) => theme.color.ink};
  overflow-wrap: anywhere;
`;

export function RejectionNotice({ rejected }: { rejected: RejectedFile[] }) {
  const heading =
    rejected.length === 1
      ? 'One file was not added'
      : `${rejected.length} files were not added`;

  return (
    // `role="status"` rather than `alert`: this is the consequence of something the person
    // just did on purpose, not an interruption, so it should not seize focus.
    <Notice role="status">
      <Heading>{heading}</Heading>
      <List>
        {rejected.map(({ file, message }) => (
          <Item key={`${file.name}-${file.size}`}>
            <Filename>{file.name}</Filename>
            {file.size > 0 && ` (${formatBytes(file.size)})`} — {message}
          </Item>
        ))}
      </List>
    </Notice>
  );
}
