import { afterEach, describe, expect, it, vi } from "vitest";

import { getAccessToken } from "@/api/client";
import {
  apiError,
  authBackend,
  bodyOf,
  DEVELOPER,
  json,
  makeSession,
  noAnswer,
  PASSWORD,
  type FakeBackend,
} from "@/test/backend";

import { REFRESH_TOKEN_KEY, type Session } from "./session";

const sessions: Session[] = [];

function sessionFor(backend: FakeBackend): Session {
  const session = makeSession(backend);
  sessions.push(session);
  return session;
}

const stored = () => window.sessionStorage.getItem(REFRESH_TOKEN_KEY);

afterEach(() => {
  for (const session of sessions.splice(0)) {
    session.dispose();
  }
  vi.useRealTimers();
});

describe("signing in", () => {
  it("keeps the access token in memory and the refresh token in this tab's storage", async () => {
    const backend = authBackend();
    const session = sessionFor(backend);

    const result = await session.signIn(DEVELOPER.email, PASSWORD);

    expect(result).toEqual({ ok: true, user: DEVELOPER });
    expect(session.getState()).toEqual({ status: "signed-in", user: DEVELOPER });
    expect(await bodyOf(backend.calls("POST /api/auth/login")[0])).toEqual({
      email: DEVELOPER.email,
      password: PASSWORD,
    });
    expect(getAccessToken()).toBe("access-1");
    expect(stored()).toBe("refresh-1");
    // Nothing in localStorage, which outlives the tab and is shared with every other one.
    expect(window.localStorage.length).toBe(0);
  });

  it("reports a refused sign-in with the API's code, and keeps nothing", async () => {
    const backend = authBackend().on("POST /api/auth/login", () =>
      apiError(401, "INVALID_CREDENTIALS", "That email or password is not correct."),
    );
    const session = sessionFor(backend);

    const result = await session.signIn(DEVELOPER.email, "wrong");

    expect(result).toEqual({
      ok: false,
      failure: {
        kind: "api",
        status: 401,
        error: {
          code: "INVALID_CREDENTIALS",
          message: "That email or password is not correct.",
          details: {},
        },
      },
    });
    expect(session.getState()).toEqual({ status: "signed-out", reason: null });
    expect(getAccessToken()).toBeNull();
    expect(stored()).toBeNull();
  });

  it("tells a server that did not answer from one that said no", async () => {
    const silent = sessionFor(authBackend().on("POST /api/auth/login", noAnswer));
    const proxied = sessionFor(
      authBackend().on("POST /api/auth/login", () => new Response("Bad gateway", { status: 502 })),
    );

    expect(await silent.signIn(DEVELOPER.email, PASSWORD)).toEqual({
      ok: false,
      failure: { kind: "unreachable" },
    });
    expect(await proxied.signIn(DEVELOPER.email, PASSWORD)).toEqual({
      ok: false,
      failure: { kind: "unreachable" },
    });
  });
});

describe("restoring after a reload", () => {
  it("starts signed out, asking nothing, when no refresh token is stored", async () => {
    const backend = authBackend();
    const session = sessionFor(backend);

    await session.restore();

    expect(session.getState()).toEqual({ status: "signed-out", reason: null });
    expect(backend.requests).toHaveLength(0);
  });

  it("trades the stored refresh token for a new pair", async () => {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "refresh-from-before");
    const backend = authBackend();
    const session = sessionFor(backend);
    expect(session.getState()).toEqual({ status: "restoring" });

    await session.restore();
    await session.restore();

    expect(session.getState()).toEqual({ status: "signed-in", user: DEVELOPER });
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(1);
    expect(await bodyOf(backend.calls("POST /api/auth/refresh")[0])).toEqual({
      refresh_token: "refresh-from-before",
    });
    expect(stored()).toBe("refresh-1");
    expect(getAccessToken()).toBe("access-1");
  });

  it("ends a refused session and says it ended, or that the account is disabled", async () => {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "revoked");
    const expired = sessionFor(
      authBackend().on("POST /api/auth/refresh", () =>
        apiError(401, "TOKEN_INVALID", "This session has been signed out. Please sign in again."),
      ),
    );
    await expired.restore();

    expect(expired.getState()).toEqual({ status: "signed-out", reason: "expired" });
    expect(stored()).toBeNull();

    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "of-a-disabled-account");
    const disabled = sessionFor(
      authBackend().on("POST /api/auth/refresh", () =>
        apiError(401, "ACCOUNT_DISABLED", "This account is disabled."),
      ),
    );
    await disabled.restore();

    expect(disabled.getState()).toEqual({ status: "signed-out", reason: "disabled" });
  });

  it("keeps the stored token when the server does not answer, for the next reload", async () => {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "still-good");
    const session = sessionFor(authBackend().on("POST /api/auth/refresh", noAnswer));

    await session.restore();

    expect(session.getState()).toEqual({ status: "signed-out", reason: "unreachable" });
    expect(stored()).toBe("still-good");
  });
});

describe("refreshing", () => {
  it("shares one refresh between everything that needs one at the same moment", async () => {
    const backend = authBackend();
    const session = sessionFor(backend);
    await session.signIn(DEVELOPER.email, PASSWORD);

    const results = await Promise.all([session.refresh(), session.refresh(), session.refresh()]);

    expect(results).toEqual([true, true, true]);
    // The first refresh revokes refresh-1, so a second one sent with it would be refused.
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(1);
    expect(getAccessToken()).toBe("access-2");
    expect(stored()).toBe("refresh-2");
  });

  it("renews the access token a minute before it expires", async () => {
    vi.useFakeTimers();
    const backend = authBackend();
    const session = sessionFor(backend);
    await session.signIn(DEVELOPER.email, PASSWORD);

    await vi.advanceTimersByTimeAsync(14 * 60_000 - 1);
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1);
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(1);
    expect(getAccessToken()).toBe("access-2");

    // And again, fourteen minutes after the renewed token was issued.
    await vi.advanceTimersByTimeAsync(14 * 60_000);
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(2);
  });

  it("keeps the session through a renewal that got no answer, and tries again", async () => {
    vi.useFakeTimers();
    let answering = false;
    const backend = authBackend();
    backend.on("POST /api/auth/refresh", () =>
      answering ? json(200, backend.tokens()) : noAnswer(),
    );
    const session = sessionFor(backend);
    await session.signIn(DEVELOPER.email, PASSWORD);

    await vi.advanceTimersByTimeAsync(14 * 60_000);
    expect(session.getState()).toEqual({ status: "signed-in", user: DEVELOPER });
    expect(getAccessToken()).toBe("access-1");

    answering = true;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(backend.calls("POST /api/auth/refresh")).toHaveLength(2);
    expect(getAccessToken()).toBe("access-2");
  });

  it("does not refresh with no session", async () => {
    const backend = authBackend();
    const session = sessionFor(backend);

    expect(await session.refresh()).toBe(false);
    expect(backend.requests).toHaveLength(0);
  });
});

describe("signing out", () => {
  it("revokes the refresh token on the server, then forgets both tokens", async () => {
    const backend = authBackend();
    const session = sessionFor(backend);
    await session.signIn(DEVELOPER.email, PASSWORD);

    await session.signOut();

    const [logout] = backend.calls("POST /api/auth/logout");
    expect(logout?.headers.get("Authorization")).toBe("Bearer access-1");
    expect(await bodyOf(logout)).toEqual({ refresh_token: "refresh-1" });
    expect(session.getState()).toEqual({ status: "signed-out", reason: "signed-out" });
    expect(getAccessToken()).toBeNull();
    expect(stored()).toBeNull();
  });

  it("still signs out when the server does not answer", async () => {
    const backend = authBackend().on("POST /api/auth/logout", noAnswer);
    const session = sessionFor(backend);
    await session.signIn(DEVELOPER.email, PASSWORD);

    await session.signOut();

    expect(session.getState()).toEqual({ status: "signed-out", reason: "signed-out" });
    expect(stored()).toBeNull();
  });

  it("renews an access token that expired, so the refresh token is revoked properly", async () => {
    const backend = authBackend();
    let first = true;
    backend.on("POST /api/auth/logout", () => {
      if (first) {
        first = false;
        return apiError(401, "TOKEN_EXPIRED", "Your session has expired.");
      }
      return new Response(null, { status: 204 });
    });
    const session = sessionFor(backend);
    await session.signIn(DEVELOPER.email, PASSWORD);

    await session.signOut();

    const logouts = backend.calls("POST /api/auth/logout");
    expect(logouts).toHaveLength(2);
    expect(logouts[1]?.headers.get("Authorization")).toBe("Bearer access-2");
    expect(await bodyOf(logouts[1])).toEqual({ refresh_token: "refresh-2" });
    expect(session.getState()).toEqual({ status: "signed-out", reason: "signed-out" });
  });
});
