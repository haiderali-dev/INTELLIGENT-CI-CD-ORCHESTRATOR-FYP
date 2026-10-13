import { QueryClient } from "@tanstack/react-query";

/**
 * Server state. Live views are kept current by WebSocket events (src/ws), which invalidate the
 * queries they affect, so nothing here polls and a refocused tab does not refetch everything.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export const queryClient = createQueryClient();
