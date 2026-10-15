import { createContext, useContext } from "react";

import { queueApi, type QueueApi } from "@/api/queueApi";

const defaultApi = queueApi();

/** The Queue page's request. The app uses the real client; a test can supply one over a fake
 * backend. */
export const QueueApiContext = createContext<QueueApi>(defaultApi);

export function useQueueApi(): QueueApi {
  return useContext(QueueApiContext);
}

export const queueKeys = {
  queue: ["queue"] as const,
};
