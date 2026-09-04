import styled from 'styled-components';

/**
 * The mark is three rules of decreasing width: the product's whole argument in nine
 * pixels. Wide, mixed input at the top narrowing to one settled value at the bottom.
 */
const Mark = styled.span`
  display: flex;
  flex-direction: column;
  gap: 2px;

  span {
    display: block;
    height: 3px;
    border-radius: ${({ theme }) => theme.radius.pill};
    background: ${({ theme }) => theme.color.ink};
  }
  span:nth-child(1) {
    width: 16px;
  }
  span:nth-child(2) {
    width: 12px;
  }
  span:nth-child(3) {
    width: 7px;
  }
`;

const Root = styled.div`
  display: inline-flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
`;

const Name = styled.span`
  font-size: 14px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.2em;
  color: ${({ theme }) => theme.color.ink};
`;

export function Wordmark() {
  return (
    <Root>
      <Mark aria-hidden="true">
        <span />
        <span />
        <span />
      </Mark>
      <Name>Distill</Name>
    </Root>
  );
}
