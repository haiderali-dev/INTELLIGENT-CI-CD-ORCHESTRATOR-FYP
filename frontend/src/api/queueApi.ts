/**
 * The Queue page's request (BUILD_PROMPT 4.4.4's `GET /api/queue`): the plugin's ranking of the
 * buildable queue, typed by the generated schema. A plugin that cannot be read is a 200 with
 * `available: false` and a reason, not an error; only a failure to reach the backend throws.
 */

import { api, type ApiClient } from "./client";
import { answer } from "./request";

export function queueApi(client: ApiClient = api) {
  return {
    queue: () => answer(client.GET("/api/queue")),
  };
}

export type QueueApi = ReturnType<typeof queueApi>;

/* What the client returns, as for the assistant pages (D-059). */
export type Queue = Awaited<ReturnType<QueueApi["queue"]>>;
export type QueueItem = Queue["items"][number];
export type UnscoredItem = Queue["unscored_items"][number];
