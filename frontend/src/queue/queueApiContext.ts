import { useApi } from "@/api/apiClientContext";
import { queueApi, type QueueApi } from "@/api/queueApi";

/** The Queue page's request, over the client in context (src/api/apiClientContext). */
export function useQueueApi(): QueueApi {
  return useApi(queueApi);
}

export const queueKeys = {
  queue: ["queue"] as const,
};
