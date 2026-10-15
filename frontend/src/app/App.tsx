import { QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";

import { queryClient } from "@/api/queryClient";
import { routes } from "@/app/routes";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import { session } from "@/auth/appSession";
import { SessionProvider } from "@/auth/SessionProvider";
import { liveEvents } from "@/ws/liveEvents";
import { LiveEventsProvider } from "@/ws/LiveEventsProvider";

const router = createBrowserRouter(routes);

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <LiveEventsProvider client={liveEvents}>
          <SessionProvider session={session} liveEvents={liveEvents} queryClient={queryClient}>
            <RouterProvider router={router} />
          </SessionProvider>
        </LiveEventsProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
