import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ThemeProvider } from 'styled-components';

import { useAppearance } from '../ui/appearance';
import { AppearanceProvider } from '../ui/AppearanceProvider';
import { GlobalStyle } from '../ui/GlobalStyle';
import { themes } from '../ui/theme';
import { makeQueryClient } from './queryClient';

/**
 * Everything the tree needs, in one place, so a test can mount a component under exactly
 * the same providers the application uses.
 */
export function Providers({
  children,
  queryClient,
}: {
  children: ReactNode;
  queryClient?: QueryClient;
}) {
  const [fallback] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient ?? fallback}>
      <AppearanceProvider>
        <Themed>{children}</Themed>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}

/**
 * The one component between the appearance preference and the palette.
 *
 * It is separate from `Providers` only because a hook cannot read a context its own
 * component provides. Everything below it re-renders on a mode change, which is the
 * intended cost and is paid once per click.
 */
function Themed({ children }: { children: ReactNode }) {
  const { mode } = useAppearance();

  return (
    <ThemeProvider theme={themes[mode]}>
      <GlobalStyle />
      {children}
    </ThemeProvider>
  );
}
