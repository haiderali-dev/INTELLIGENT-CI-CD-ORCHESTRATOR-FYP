import type { QueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import type { LiveEventsClient } from "@/ws/LiveEventsClient";

import type { Session } from "./session";
import { SessionContext } from "./sessionContext";

/**
 * Provides the session, restores it on load, and keeps everything that depends on who is signed in
 * in step with it:
 * - the live-events connection is reopened with the new token on sign-in, and closed on sign-out;
 * - cached server data is dropped on sign-out, so the next person never sees the last one's;
 * - a connection the server refused (close 1008) while the session stands gets one refresh and
 *   one more try. A second refusal before the connection opens is left alone, not looped on.
 */
export function SessionProvider({
  session,
  liveEvents,
  queryClient,
  children,
}: {
  session: Session;
  liveEvents?: LiveEventsClient;
  queryClient?: QueryClient;
  children: ReactNode;
}) {
  useEffect(() => {
    void session.restore();
  }, [session]);

  useEffect(() => {
    let previous = session.getState().status;
    return session.subscribe(() => {
      const { status } = session.getState();
      if (status === previous) {
        return;
      }
      previous = status;
      if (status === "signed-in") {
        liveEvents?.restart();
      } else if (status === "signed-out") {
        liveEvents?.restart();
        queryClient?.clear();
      }
    });
  }, [session, liveEvents, queryClient]);

  useEffect(() => {
    if (!liveEvents) {
      return undefined;
    }
    let retried = false;
    return liveEvents.onStatus((status) => {
      if (status === "open") {
        retried = false;
        return;
      }
      if (status !== "signed-out" || retried || session.getState().status !== "signed-in") {
        return;
      }
      retried = true;
      void session.refresh().then((renewed) => {
        if (renewed) {
          liveEvents.restart();
        }
      });
    });
  }, [session, liveEvents]);

  return <SessionContext value={session}>{children}</SessionContext>;
}
