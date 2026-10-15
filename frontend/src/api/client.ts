/**
 * The typed API client. Every path, parameter and response type comes from `schema.d.ts`, which
 * `npm run generate:api` writes from `openapi.json`, the backend's own schema
 * (`python -m app.openapi_export`). BUILD_PROMPT 4.7.1: never hand-write API types.
 *
 * Tokens (T6.3, D-054). The access token lives here, in memory only. When a request comes back
 * 401, the client asks the session for a new access token once and repeats the request, so a page
 * never sees an expired token as an error. The session (src/auth) registers how to refresh.
 */

import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type ApiClient = ReturnType<typeof createClient<paths>>;

/** The one error shape every endpoint returns (backend `app/core/errors.py`, D-055). */
export type ApiErrorBody = components["schemas"]["ErrorBody"];
export type ErrorCode = components["schemas"]["ErrorCode"];

/** The backend's origin, or "" for the app's own origin (the dev server proxies /api). */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

let accessToken: string | null = null;
let refreshAccessToken: (() => Promise<boolean>) | null = null;

/** Held in memory only: never in storage, where any script on the page could read it. */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/**
 * How to get a new access token after a 401. The session registers its refresh here; it resolves
 * true when a new token is in place, and false when there is none to be had.
 */
export function setTokenRefresher(refresher: (() => Promise<boolean>) | null): void {
  refreshAccessToken = refresher;
}

export const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (accessToken) {
      request.headers.set("Authorization", `Bearer ${accessToken}`);
    }
    return request;
  },
};

/** openapi-fetch calls fetch with the request and, in some runtimes, extra init to pass along. */
type Fetch = (request: Request, init?: RequestInit) => Promise<Response>;

/** The auth endpoints answer 401 for their own reasons, a wrong password or a dead refresh token,
 * so a 401 from them is an answer, never a reason to refresh. */
function isAuthEndpoint(url: string): boolean {
  return new URL(url, "http://localhost").pathname.startsWith("/api/auth/");
}

/** Repeats a request once, with a new access token, when it came back 401. */
export function withTokenRefresh(send: Fetch): Fetch {
  return async (request: Request, init?: RequestInit) => {
    // Cloned before sending, because sending consumes the body.
    const retry = refreshAccessToken && !isAuthEndpoint(request.url) ? request.clone() : null;
    const response = await send(request, init);
    if (response.status !== 401 || !retry || !refreshAccessToken) {
      return response;
    }
    if (!(await refreshAccessToken()) || !accessToken) {
      return response;
    }
    retry.headers.set("Authorization", `Bearer ${accessToken}`);
    return send(retry, init);
  };
}

export function createApiClient(options: { baseUrl?: string; fetch?: Fetch } = {}): ApiClient {
  // Read at call time, not at creation, so the browser's fetch is whatever it is when used.
  const send: Fetch = options.fetch ?? ((request, init) => globalThis.fetch(request, init));
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? API_BASE_URL,
    fetch: withTokenRefresh(send),
  });
  client.use(authMiddleware);
  return client;
}

export const api = createApiClient();
