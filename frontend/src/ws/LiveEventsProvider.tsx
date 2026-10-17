import { useEffect, type ReactNode } from "react";

import type { LiveEventsClient } from "./LiveEventsClient";
import { LiveEventsContext } from "./liveEventsContext";

/** Starts the client while mounted. With no access token yet it reports "signed-out" and waits for
 * `restart()`, which sign-in calls (T6.3). */
export function LiveEventsProvider({
  client,
  children,
}: {
  client: LiveEventsClient;
  children: ReactNode;
}) {
  useEffect(() => {
    client.start();
    return () => {
      client.stop();
    };
  }, [client]);

  return <LiveEventsContext value={client}>{children}</LiveEventsContext>;
}
