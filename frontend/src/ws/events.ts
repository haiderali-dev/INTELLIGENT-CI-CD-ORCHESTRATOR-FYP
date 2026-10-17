/**
 * The WebSocket protocol of `WS /ws` (backend `app/ws/routes.py` and `app/ws/hub.py`).
 *
 * WebSocket messages are not part of the OpenAPI schema, so these names are written here once, by
 * hand, and `scripts/verify.py --phase 6` fails when they drift from the backend's `EventType` and
 * `Topic` enums.
 */

export const LIVE_EVENT_TYPES = [
  "run.started",
  "run.updated",
  "run.finished",
  "run.queued",
  "chain.updated",
  "chain.finished",
  "chain.stages",
  "queue.changed",
  "notification",
  "hello",
  "heartbeat",
  "error",
] as const;
export type LiveEventType = (typeof LIVE_EVENT_TYPES)[number];

export const LIVE_TOPICS = ["runs", "queue", "notifications", "system"] as const;
export type LiveTopic = (typeof LIVE_TOPICS)[number];

/** Every message after authentication: `{"type", "sentAt", "data"}`. */
export interface LiveEvent {
  type: LiveEventType;
  sentAt: string;
  data: Record<string, unknown>;
}

/** The one frame a client sends: within 10 seconds of connecting, before anything is delivered. */
export interface AuthFrame {
  type: "auth";
  token: string;
  topics: readonly LiveTopic[];
}

/** Bad or missing token: stop, and sign in again. */
export const CLOSE_POLICY = 1008;
/** A fault on the server: retry with backoff. */
export const CLOSE_INTERNAL = 1011;

export function parseLiveEvent(raw: unknown): LiveEvent | null {
  if (typeof raw !== "string") {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const { type, sentAt, data } = value as Record<string, unknown>;
  if (!LIVE_EVENT_TYPES.includes(type as LiveEventType) || typeof sentAt !== "string") {
    return null;
  }
  const payload = typeof data === "object" && data !== null ? (data as Record<string, unknown>) : {};
  return { type: type as LiveEventType, sentAt, data: payload };
}
