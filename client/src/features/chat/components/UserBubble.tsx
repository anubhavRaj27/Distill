import styled from 'styled-components';

/**
 * A question, as asked.
 *
 * Right-aligned and on sunken paper rather than raised: the person's own words are the one
 * thing on this screen that needs no verifying, so they sit back rather than forward.
 */
const Row = styled.div`
  display: flex;
  justify-content: flex-end;
`;

const Bubble = styled.div`
  max-width: 620px;
  padding: 10px 16px;

  font-size: 14px;
  line-height: 1.6;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperSunken};
  border-radius: ${({ theme }) => theme.radius.md};
  /* A pasted paragraph keeps its line breaks instead of collapsing into one block. */
  white-space: pre-wrap;
  overflow-wrap: anywhere;
`;

export function UserBubble({ text }: { text: string }) {
  return (
    <Row>
      <Bubble>{text}</Bubble>
    </Row>
  );
}
