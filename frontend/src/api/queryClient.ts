import { QueryClient } from "@tanstack/react-query";

/**
 * Server state. Live views are kept current by WebSocket events (src/ws), which invalidate the
 * queries they affect, so nothing polls by default and a refocused tab does not refetch everything.
 * The queue alone also asks every 10 seconds, because time changes it between events (D-060).
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
