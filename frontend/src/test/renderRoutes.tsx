import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { assistantApi } from "@/api/assistantApi";
import { createApiClient, getAccessToken } from "@/api/client";
import { queueApi } from "@/api/queueApi";
import { routes } from "@/app/routes";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import type { Session } from "@/auth/session";
import { SessionProvider } from "@/auth/SessionProvider";
import { ToastProvider } from "@/components/toast/ToastProvider";
import { QueueApiContext } from "@/queue/queueApiContext";
import { AssistantApiContext } from "@/workspace/assistantApiContext";
import { LiveEventsClient } from "@/ws/LiveEventsClient";
import { LiveEventsProvider } from "@/ws/LiveEventsProvider";

import { BASE_URL, FakeBackend } from "./backend";
import { FakeSocket } from "./fakeSocket";

/**
 * The whole route tree at `path`, inside the same providers as the app (src/app/App.tsx), around
 * the given session. Requests go to `backend`, which answers nothing it was not told to. The live
 * events connect through a `FakeSocket` the test can play the server on.
 */
export function renderRoutes(path: string, session: Session, backend = new FakeBackend()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  // No retries: a failure should show at once, and fail the test if it should not have happened.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 5_000 }, mutations: { retry: false } },
  });
  const liveEvents = new LiveEventsClient({
    url: "ws://backend.test/ws",
    getToken: getAccessToken,
    topics: ["runs", "queue"],
    createSocket: (url) => new FakeSocket(url),
  });
  const client = createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch });

  const view = render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <LiveEventsProvider client={liveEvents}>
          <SessionProvider session={session} liveEvents={liveEvents} queryClient={queryClient}>
            <AssistantApiContext value={assistantApi(client)}>
              <QueueApiContext value={queueApi(client)}>
                <ToastProvider>
                  <RouterProvider router={router} />
                </ToastProvider>
              </QueueApiContext>
            </AssistantApiContext>
          </SessionProvider>
        </LiveEventsProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { router, queryClient, liveEvents, ...view };
}

/** Where the router is now, as one string. */
export function currentPath(router: ReturnType<typeof createMemoryRouter>): string {
  const { pathname, search } = router.state.location;
  return `${pathname}${search}`;
}
