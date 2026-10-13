import { createContext, useContext, useEffect, useRef, useSyncExternalStore } from "react";

import type { LiveEvent, LiveEventType } from "./events";
import type { LiveEventsClient, LiveStatus } from "./LiveEventsClient";

export const LiveEventsContext = createContext<LiveEventsClient | null>(null);

function useClient(): LiveEventsClient {
  const client = useContext(LiveEventsContext);
  if (!client) {
    throw new Error("live events need a <LiveEventsProvider> above them");
  }
  return client;
}

/** Calls `handler` for each event of the given types, with the latest handler every time. */
export function useLiveEvent(
  types: LiveEventType | readonly LiveEventType[],
  handler: (event: LiveEvent) => void,
): void {
  const client = useClient();
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  const key = typeof types === "string" ? types : types.join(" ");
  useEffect(() => {
    const wanted = new Set(key.split(" "));
    return client.subscribe((event) => {
      if (wanted.has(event.type)) {
        latest.current(event);
      }
    });
  }, [client, key]);
}

export function useLiveStatus(): LiveStatus {
  const client = useClient();
  return useSyncExternalStore(client.onStatus, client.getStatus, client.getStatus);
}
