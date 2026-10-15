import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeSocket } from "@/test/fakeSocket";

import { CLOSE_POLICY, parseLiveEvent, type LiveEvent } from "./events";
import { LiveEventsClient, liveEventsUrl } from "./LiveEventsClient";

const WS_URL = "ws://backend.test/ws";
const hello = (heartbeatSeconds = 25) => ({
  type: "hello",
  sentAt: "2026-10-14T10:00:00Z",
  data: { subscriberId: "abc", topics: ["queue", "runs"], heartbeatSeconds },
});
const latest = () => FakeSocket.opened.at(-1) ?? null;

function makeClient(token: string | null = "access-token") {
  return new LiveEventsClient({
    url: WS_URL,
    getToken: () => token,
    topics: ["runs", "queue"],
    createSocket: (url) => new FakeSocket(url),
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.opened = [];
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LiveEventsClient", () => {
  it("authenticates in its first frame, never in the URL", () => {
    const client = makeClient();
    client.start();
    const socket = latest();
    socket?.accept();

    expect(socket?.url).toBe(WS_URL);
    expect(socket?.sent.map((frame) => JSON.parse(frame) as unknown)).toEqual([
      { type: "auth", token: "access-token", topics: ["runs", "queue"] },
    ]);
    expect(client.getStatus()).toBe("connecting");
    client.stop();
  });

  it("is open once the server says hello, and passes on every event but heartbeats", () => {
    const client = makeClient();
    const received: LiveEvent[] = [];
    client.subscribe((event) => received.push(event));
    client.start();
    const socket = latest();
    socket?.accept();

    socket?.deliver(hello());
    socket?.deliver({ type: "heartbeat", sentAt: "2026-10-14T10:00:25Z", data: {} });
    socket?.deliver({ type: "queue.changed", sentAt: "2026-10-14T10:00:26Z", data: { length: 3 } });
    socket?.deliver("not json");

    expect(client.getStatus()).toBe("open");
    expect(received.map((event) => event.type)).toEqual(["hello", "queue.changed"]);
    expect(received[1]?.data).toEqual({ length: 3 });
    client.stop();
  });

  it("stops for good when the token is refused (1008)", () => {
    const client = makeClient();
    client.start();
    latest()?.drop(CLOSE_POLICY);

    vi.advanceTimersByTime(120_000);

    expect(client.getStatus()).toBe("signed-out");
    expect(FakeSocket.opened).toHaveLength(1);
    client.stop();
  });

  it("reconnects after any other close, doubling the wait each time", () => {
    const client = makeClient();
    client.start();

    latest()?.drop(1011);
    expect(client.getStatus()).toBe("reconnecting");
    vi.advanceTimersByTime(999);
    expect(FakeSocket.opened).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.opened).toHaveLength(2);

    latest()?.drop(1006);
    vi.advanceTimersByTime(1_999);
    expect(FakeSocket.opened).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.opened).toHaveLength(3);

    // A successful connection starts the backoff over.
    latest()?.accept();
    latest()?.deliver(hello());
    latest()?.drop(1006);
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.opened).toHaveLength(4);
    client.stop();
  });

  it("never waits more than thirty seconds between attempts", () => {
    const client = makeClient();
    client.start();
    for (let attempt = 0; attempt < 8; attempt += 1) {
      latest()?.drop(1006);
      vi.advanceTimersByTime(30_000);
    }
    expect(FakeSocket.opened).toHaveLength(9);
    client.stop();
  });

  it("closes a connection that has gone quiet, then reconnects", () => {
    const client = makeClient();
    client.start();
    const first = latest();
    first?.accept();
    first?.deliver(hello(1));

    vi.advanceTimersByTime(6_999);
    expect(first?.closedWith).toBeUndefined();
    vi.advanceTimersByTime(1);
    expect(first?.closedWith).toBe(4000);

    first?.drop(4000);
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.opened).toHaveLength(2);
    client.stop();
  });

  it("opens nothing without a token, and says why", () => {
    const client = makeClient(null);
    client.start();

    expect(FakeSocket.opened).toHaveLength(0);
    expect(client.getStatus()).toBe("signed-out");
  });

  it("reports its status changes, and stopping ignores the close that follows", () => {
    const client = makeClient();
    const statuses: string[] = [];
    client.onStatus((status) => statuses.push(status));
    client.start();
    const socket = latest();
    socket?.accept();
    socket?.deliver(hello());

    client.stop();
    socket?.drop(1000);
    vi.advanceTimersByTime(60_000);

    expect(socket?.closedWith).toBe(1000);
    expect(statuses).toEqual(["connecting", "open", "idle"]);
    expect(FakeSocket.opened).toHaveLength(1);
  });
});

describe("liveEventsUrl", () => {
  it.each([
    ["", { protocol: "http:", host: "localhost:5173" }, "ws://localhost:5173/ws"],
    ["", { protocol: "https:", host: "demo.example" }, "wss://demo.example/ws"],
    ["http://localhost:8000", { protocol: "http:", host: "localhost:5173" }, "ws://localhost:8000/ws"],
  ])("base %j on %o is %s", (base, location, expected) => {
    expect(liveEventsUrl(base, location)).toBe(expected);
  });
});

describe("parseLiveEvent", () => {
  it.each([
    ["not JSON", "{"],
    ["not an object", "[1, 2]"],
    ["an unknown type", JSON.stringify({ type: "run.exploded", sentAt: "x", data: {} })],
    ["no sentAt", JSON.stringify({ type: "run.updated", data: {} })],
  ])("refuses %s", (_label, raw) => {
    expect(parseLiveEvent(raw)).toBeNull();
  });

  it("gives an event with no data an empty object", () => {
    expect(parseLiveEvent(JSON.stringify({ type: "run.started", sentAt: "t" }))).toEqual({
      type: "run.started",
      sentAt: "t",
      data: {},
    });
  });
});
