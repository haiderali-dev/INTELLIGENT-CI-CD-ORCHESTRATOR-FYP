import { afterEach, describe, expect, it } from "vitest";

import { createApiClient, setAccessToken } from "./client";

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

afterEach(() => {
  setAccessToken(null);
});

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
