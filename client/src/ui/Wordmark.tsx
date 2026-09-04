import styled from 'styled-components';

/**
 * The mark: a drop falling through a ring and settling as a single point below it. The
 * product's argument in twenty pixels — a mixed pile narrowed to one clean value.
 *
 * Replaces the earlier three-descending-bars mark (September 5, 2026), which read as a
 * filter but sat awkwardly beside a serif wordmark at header size.
 */
const Glyph = styled.svg`
  width: 20px;
  height: 20px;
  color: ${({ theme }) => theme.color.ink};
  flex-shrink: 0;
`;

const Root = styled.div`
  display: inline-flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
  flex-shrink: 0;
`;

const Name = styled.span`
  font-family: ${({ theme }) => theme.font.display};
  font-size: 17px;
  line-height: 1;
  color: ${({ theme }) => theme.color.ink};
`;

export function Wordmark() {
  return (
    <Root>
      <Glyph viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M10 5.5 L10 11.5 M7.5 8.5 L10 11.5 L12.5 8.5"
          stroke="currentColor"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="10" cy="13.5" r="0.9" fill="currentColor" />
      </Glyph>
      <Name>Distill</Name>
    </Root>
  );
}
