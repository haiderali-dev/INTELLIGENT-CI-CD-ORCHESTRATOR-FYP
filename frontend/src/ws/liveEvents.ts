import { API_BASE_URL, getAccessToken } from "@/api/client";

import { LIVE_TOPICS } from "./events";
import { LiveEventsClient, liveEventsUrl } from "./LiveEventsClient";

/** The app's single connection, shared by every page. It asks for every topic: the server
 * delivers a published event only to subscribers of its topic, "system" included. */
export const liveEvents = new LiveEventsClient({
  url: liveEventsUrl(API_BASE_URL, window.location),
  getToken: getAccessToken,
  topics: LIVE_TOPICS,
});
