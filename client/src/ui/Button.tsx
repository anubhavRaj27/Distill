import styled, { css } from 'styled-components';

export type ButtonVariant = 'primary' | 'secondary' | 'quiet';

/**
 * The one button in the app.
 *
 * Variants are a fixed union rather than free-form props, so styled-components generates a
 * bounded number of classes no matter how many buttons render. This is the same constraint
 * the table cells will live under (implementation.md section 2.3), applied early so the
 * pattern is established rather than retrofitted.
 *
 * There is no Radix primitive here on purpose: a button that is a `<button>` already has
 * the semantics and keyboard behaviour a primitive would supply. Radix earns its place
 * where behaviour is genuinely hard — dialogs, menus, tooltips, focus traps — which is the
 * next slice of the kit, not this one.
 */
export const Button = styled.button<{ $variant?: ButtonVariant }>`
  appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: ${({ theme }) => theme.space.sm};

  min-height: 44px;
  padding: 0 ${({ theme }) => theme.space.xl};

  font-family: inherit;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;

  border-radius: ${({ theme }) => theme.radius.sm};
  cursor: pointer;
  transition:
    background-color ${({ theme }) => theme.motion.quick},
    border-color ${({ theme }) => theme.motion.quick},
    color ${({ theme }) => theme.motion.quick};

  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  ${({ $variant = 'primary' }) => VARIANTS[$variant]}
`;

const VARIANTS: Record<ButtonVariant, ReturnType<typeof css>> = {
  primary: css`
    background: ${({ theme }) => theme.color.inkSurface};
    color: ${({ theme }) => theme.color.onInk};
    border: 1px solid ${({ theme }) => theme.color.inkSurface};

    &:hover:not(:disabled) {
      background: ${({ theme }) => theme.color.inkSurfaceHover};
      border-color: ${({ theme }) => theme.color.inkSurfaceHover};
    }
  `,
  secondary: css`
    background: ${({ theme }) => theme.color.paperRaised};
    color: ${({ theme }) => theme.color.ink};
    border: 1px solid ${({ theme }) => theme.color.ink};

    &:hover:not(:disabled) {
      background: ${({ theme }) => theme.color.paperSunken};
    }
  `,
  quiet: css`
    background: transparent;
    color: ${({ theme }) => theme.color.inkMuted};
    border: 1px solid transparent;
    font-weight: 500;

    &:hover:not(:disabled) {
      color: ${({ theme }) => theme.color.ink};
    }
  `,
};
