import { QueryClient } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAccessToken } from "@/api/client";
import { authBackend, DEVELOPER, makeSession, PASSWORD } from "@/test/backend";
import { FakeSocket } from "@/test/fakeSocket";
import { CLOSE_POLICY } from "@/ws/events";
import { LiveEventsClient } from "@/ws/LiveEventsClient";

import type { Session } from "./session";
import { SessionProvider } from "./SessionProvider";

const hello = {
  type: "hello",
  sentAt: "2026-10-15T10:00:00Z",
  data: { subscriberId: "abc", topics: ["runs"], heartbeatSeconds: 25 },
};

let session: Session | undefined;
let live: LiveEventsClient | undefined;

function setup() {
  const backend = authBackend();
  session = makeSession(backend);
  live = new LiveEventsClient({
    url: "ws://backend.test/ws",
    getToken: getAccessToken,
    topics: ["runs"],
    createSocket: (url) => new FakeSocket(url),
  });
  const queryClient = new QueryClient();
  const cleared = vi.spyOn(queryClient, "clear");
  render(
    <SessionProvider session={session} liveEvents={live} queryClient={queryClient}>
      <p>app</p>
    </SessionProvider>,
  );
  // What LiveEventsProvider does on mount: with no token yet, the client waits, signed out.
  live.start();
  return { backend, session, live, cleared };
}

const authFrame = (socket: FakeSocket | null) => JSON.parse(socket?.sent[0] ?? "null") as unknown;

beforeEach(() => {
  FakeSocket.opened = [];
});

afterEach(() => {
  live?.stop();
  session?.dispose();
});

describe("SessionProvider", () => {
  it("opens the live connection with the new token on sign-in, and closes it on sign-out", async () => {
    const { session, live, cleared } = setup();
    expect(live.getStatus()).toBe("signed-out");
    expect(FakeSocket.opened).toHaveLength(0);

    await act(() => session.signIn(DEVELOPER.email, PASSWORD));
    const socket = FakeSocket.latest();
    socket?.accept();

    expect(authFrame(socket)).toEqual({ type: "auth", token: "access-1", topics: ["runs"] });

    await act(() => session.signOut());

    expect(socket?.closedWith).toBe(1000);
    expect(live.getStatus()).toBe("signed-out");
    expect(FakeSocket.opened).toHaveLength(1);
    // The next person must never see the last one's data.
    expect(cleared).toHaveBeenCalled();
  });

  it("refreshes once and reconnects when the server refuses the connection's token", async () => {
    const { backend, session } = setup();
    await act(() => session.signIn(DEVELOPER.email, PASSWORD));
    const first = FakeSocket.latest();
    first?.accept();
    first?.deliver(hello);

    act(() => {
      first?.drop(CLOSE_POLICY);
    });

    await vi.waitFor(() => {
      expect(FakeSocket.opened).toHaveLength(2);
    });
    const second = FakeSocket.latest();
    second?.accept();
    expect(authFrame(second)).toEqual({ type: "auth", token: "access-2", topics: ["runs"] });
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(1);

    // Refused again before it ever opened: that is not a token problem a refresh can fix, so the
    // provider stops rather than loop.
    act(() => {
      second?.drop(CLOSE_POLICY);
    });
    await act(() => Promise.resolve());

    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(1);
    expect(FakeSocket.opened).toHaveLength(2);
  });
});
