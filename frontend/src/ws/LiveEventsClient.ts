/**
 * The app's one WebSocket connection (BUILD_PROMPT 4.7.1: "one WebSocket client for live events").
 *
 * - **Authentication** is the first frame, never the URL: a token in a query string ends up in
 *   proxy logs and browser history (backend `app/ws/routes.py`).
 * - **Close 1008** means the token was refused: the client stops and reports "signed-out" rather
 *   than retrying a token that will be refused again.
 * - **Any other close** is retried with exponential backoff, from one second up to thirty.
 * - **A silent connection** is treated as a dead one. The server sends a heartbeat when idle, and
 *   says how often in its hello. Nothing for two heartbeats and a margin closes the socket, which
 *   then reconnects like any other drop.
 */

import {
  CLOSE_POLICY,
  parseLiveEvent,
  type AuthFrame,
  type LiveEvent,
  type LiveTopic,
} from "./events";

export type LiveStatus = "idle" | "connecting" | "open" | "reconnecting" | "signed-out";

/** The part of the browser's WebSocket this client uses, so tests can supply a fake. */
export interface SocketLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export interface LiveEventsOptions {
  url: string;
  getToken: () => string | null;
  topics: readonly LiveTopic[];
  createSocket?: (url: string) => SocketLike;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
}

const DEFAULT_HEARTBEAT_MS = 25_000;
const WATCHDOG_MARGIN_MS = 5_000;
/** Ours to send: the browser accepts 1000 or 3000 to 4999 from a page. */
const CLOSE_HEARTBEAT_MISSED = 4000;
const CLOSE_NORMAL = 1000;

type Listener = (event: LiveEvent) => void;
type StatusListener = (status: LiveStatus) => void;

export class LiveEventsClient {
  private readonly options: Required<Omit<LiveEventsOptions, "createSocket">> &
    Pick<LiveEventsOptions, "createSocket">;
  private socket: SocketLike | null = null;
  private status: LiveStatus = "idle";
  private running = false;
  private attempt = 0;
  private heartbeatMs = DEFAULT_HEARTBEAT_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private watchdogTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly listeners = new Set<Listener>();
  private readonly statusListeners = new Set<StatusListener>();

  constructor(options: LiveEventsOptions) {
    this.options = { initialBackoffMs: 1_000, maxBackoffMs: 30_000, ...options };
  }

  /** Connects, or reports "signed-out" when there is no token to connect with. */
  start(): void {
    this.running = true;
    this.attempt = 0;
    this.connect();
  }

  stop(): void {
    this.running = false;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    socket?.close(CLOSE_NORMAL, "client stopped");
    this.setStatus("idle");
  }

  /** After signing in or out: drop the current connection and start over with the new token. */
  restart(): void {
    this.stop();
    this.start();
  }

  getStatus = (): LiveStatus => this.status;

  /** Every event except heartbeats; returns an unsubscribe. */
  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  onStatus = (listener: StatusListener): (() => void) => {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  };

  private connect(): void {
    if (!this.running) {
      return;
    }
    const token = this.options.getToken();
    if (!token) {
      this.setStatus("signed-out");
      return;
    }
    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting");

    const create = this.options.createSocket ?? ((url: string) => new WebSocket(url));
    const socket = create(this.options.url);
    this.socket = socket;

    socket.onopen = () => {
      const frame: AuthFrame = { type: "auth", token, topics: this.options.topics };
      socket.send(JSON.stringify(frame));
      this.armWatchdog();
    };
    socket.onmessage = (message) => {
      if (socket !== this.socket) {
        return;
      }
      const event = parseLiveEvent(message.data);
      if (!event) {
        return;
      }
      if (event.type === "hello") {
        const seconds = event.data.heartbeatSeconds;
        if (typeof seconds === "number" && seconds > 0) {
          this.heartbeatMs = seconds * 1000;
        }
        this.attempt = 0;
        this.setStatus("open");
      }
      // After a hello, so the first wait already uses the server's heartbeat.
      this.armWatchdog();
      if (event.type === "heartbeat") {
        return;
      }
      for (const listener of this.listeners) {
        listener(event);
      }
    };
    socket.onclose = (close) => {
      if (socket !== this.socket) {
        return;
      }
      this.socket = null;
      this.clearTimers();
      if (!this.running) {
        return;
      }
      if (close.code === CLOSE_POLICY) {
        this.setStatus("signed-out");
        return;
      }
      this.scheduleReconnect();
    };
    // An error is always followed by a close, which decides what happens next.
    socket.onerror = () => undefined;
  }

  private scheduleReconnect(): void {
    const { initialBackoffMs, maxBackoffMs } = this.options;
    const delay = Math.min(maxBackoffMs, initialBackoffMs * 2 ** this.attempt);
    this.attempt += 1;
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, delay);
  }

  private armWatchdog(): void {
    clearTimeout(this.watchdogTimer);
    this.watchdogTimer = setTimeout(() => {
      this.socket?.close(CLOSE_HEARTBEAT_MISSED, "no heartbeat");
    }, this.heartbeatMs * 2 + WATCHDOG_MARGIN_MS);
  }

  private clearTimers(): void {
    clearTimeout(this.reconnectTimer);
    clearTimeout(this.watchdogTimer);
    this.reconnectTimer = undefined;
    this.watchdogTimer = undefined;
  }

  private setStatus(status: LiveStatus): void {
    if (status === this.status) {
      return;
    }
    this.status = status;
    for (const listener of this.statusListeners) {
      listener(status);
    }
  }
}

/** `ws://` or `wss://` for `/ws` on the backend's origin, or on the page's own. */
export function liveEventsUrl(apiBaseUrl: string, location: Pick<Location, "protocol" | "host">): string {
  const origin = apiBaseUrl || `${location.protocol}//${location.host}`;
  const url = new URL("/ws", origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
