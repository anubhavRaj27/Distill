import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ThemeProvider } from 'styled-components';

import { GlobalStyle } from '../ui/GlobalStyle';
import { theme } from '../ui/theme';
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
      <ThemeProvider theme={theme}>
        <GlobalStyle />
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
