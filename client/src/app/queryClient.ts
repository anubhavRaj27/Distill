import { QueryClient } from '@tanstack/react-query';

/**
 * Server-state defaults, in their own module so `Providers.tsx` exports components only
 * and Fast Refresh keeps working.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Server state in this product is pushed, not polled: the event stream mutates the
        // cache directly with `setQueryData` (implementation.md section 8.1). Refetching on
        // focus would fight that and make the table flicker mid-stream.
        refetchOnWindowFocus: false,
        staleTime: 30_000,
        retry: 1,
      },
      mutations: {
        // A failed upload or workspace creation is reported to the person, who decides
        // whether to try again. Silently retrying a multipart upload is not a favour.
        retry: 0,
      },
    },
  });
}
