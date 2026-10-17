import { describe, expect, it, vi } from "vitest";

import { apiError, BASE_URL, bodyOf, DEVELOPER, FakeBackend, json } from "@/test/backend";

import { createApiClient, setAccessToken, setTokenRefresher } from "./client";

function recordingFetch() {
  const requests: Request[] = [];
  const fetch = (input: Request): Promise<Response> => {
    requests.push(input);
    return Promise.resolve(
      new Response(JSON.stringify({ status: "up" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  };
  return { requests, fetch };
}

/** A refresher that hands out `fresh` as the new access token. */
function refresherGiving(fresh: string | null) {
  return vi.fn(() => {
    if (fresh) {
      setAccessToken(fresh);
    }
    return Promise.resolve(fresh !== null);
  });
}

/** Answers `route` with 401 for the first `times` calls, then with `then`. */
function expiringBackend(route: string, times: number, then: () => Response): FakeBackend {
  let refused = 0;
  return new FakeBackend().on(route, () => {
    if (refused < times) {
      refused += 1;
      return apiError(401, "TOKEN_EXPIRED", "Your session has expired.");
    }
    return then();
  });
}

const authorizations = (requests: Request[]) =>
  requests.map((request) => request.headers.get("Authorization"));

describe("api client", () => {
  it("calls the backend's paths, with no token until one is set", async () => {
    const { requests, fetch } = recordingFetch();
    const client = createApiClient({ baseUrl: "http://backend.test", fetch });

    await client.GET("/api/health/live");

    expect(requests[0]?.url).toBe("http://backend.test/api/health/live");
    expect(requests[0]?.headers.get("Authorization")).toBeNull();
  });

  it("sends the access token as a bearer token once one is set", async () => {
    const { requests, fetch } = recordingFetch();
    const client = createApiClient({ baseUrl: "http://backend.test", fetch });

    setAccessToken("access-token");
    await client.GET("/api/me");
    setAccessToken(null);
    await client.GET("/api/me");

    expect(requests.map((request) => request.headers.get("Authorization"))).toEqual([
      "Bearer access-token",
      null,
    ]);
  });
});

describe("api client after a 401", () => {
  it("gets a new access token and repeats the request once with it", async () => {
    const backend = expiringBackend("GET /api/me", 1, () => json(200, DEVELOPER));
    const client = createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch });
    const refresher = refresherGiving("fresh");
    setAccessToken("stale");
    setTokenRefresher(refresher);

    const { data, error } = await client.GET("/api/me");

    expect(error).toBeUndefined();
    expect(data).toEqual(DEVELOPER);
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(authorizations(backend.requests)).toEqual(["Bearer stale", "Bearer fresh"]);
  });

  it("sends the same body again", async () => {
    const created = { ...DEVELOPER, id: "user-2", email: "new@example.com", created_at: "now" };
    const backend = expiringBackend("POST /api/admin/users", 1, () => json(201, created));
    const client = createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch });
    setAccessToken("stale");
    setTokenRefresher(refresherGiving("fresh"));
    const body = { email: "new@example.com", password: "a long enough password", role: "DEVELOPER" as const };

    await client.POST("/api/admin/users", { body });

    expect(backend.requests).toHaveLength(2);
    expect(await bodyOf(backend.requests[0])).toEqual(body);
    expect(await bodyOf(backend.requests[1])).toEqual(body);
  });

  it("returns the 401 when no new token can be had", async () => {
    const backend = expiringBackend("GET /api/me", 1, () => json(200, DEVELOPER));
    const client = createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch });
    setAccessToken("stale");
    setTokenRefresher(refresherGiving(null));

    const { data, response } = await client.GET("/api/me");

    expect(data).toBeUndefined();
    expect(response.status).toBe(401);
    expect(backend.requests).toHaveLength(1);
  });

  it("repeats a request only once", async () => {
    const backend = expiringBackend("GET /api/me", 2, () => json(200, DEVELOPER));
    const client = createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch });
    const refresher = refresherGiving("fresh");
    setAccessToken("stale");
    setTokenRefresher(refresher);

    const { response } = await client.GET("/api/me");

    expect(response.status).toBe(401);
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(backend.requests).toHaveLength(2);
  });

  it("takes the auth endpoints' own 401s as answers, never as a reason to refresh", async () => {
    const backend = new FakeBackend().on("POST /api/auth/login", () =>
      apiError(401, "INVALID_CREDENTIALS", "That email or password is not correct."),
    );
    const client = createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch });
    const refresher = refresherGiving("fresh");
    setTokenRefresher(refresher);

    const { response } = await client.POST("/api/auth/login", {
      body: { email: DEVELOPER.email, password: "wrong" },
    });

    expect(response.status).toBe(401);
    expect(refresher).not.toHaveBeenCalled();
    expect(backend.requests).toHaveLength(1);
  });
});
