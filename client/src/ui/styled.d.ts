/**
 * Teaches styled-components what `props.theme` is, so every template literal in the app is
 * type-checked against `ui/theme.ts` rather than accepting any string.
 */

import type { Theme } from './theme';

declare module 'styled-components' {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  export interface DefaultTheme extends Theme {}
}
