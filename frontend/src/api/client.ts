/**
 * The typed API client. Every path, parameter and response type comes from `schema.d.ts`, which
 * `npm run generate:api` writes from `openapi.json`, the backend's own schema
 * (`python -m app.openapi_export`). BUILD_PROMPT 4.7.1: never hand-write API types.
 *
 * Sign-in and token refresh are T6.3. This module holds only where the access token lives and the
 * middleware that sends it.
 */

import createClient, { type ClientOptions, type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

export type ApiClient = ReturnType<typeof createClient<paths>>;

/** The backend's origin, or "" for the app's own origin (the dev server proxies /api). */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

let accessToken: string | null = null;

/** Held in memory only: never in storage, where any script on the page could read it. */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (accessToken) {
      request.headers.set("Authorization", `Bearer ${accessToken}`);
    }
    return request;
  },
};

export function createApiClient(
  options: { baseUrl?: string; fetch?: ClientOptions["fetch"] } = {},
): ApiClient {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? API_BASE_URL,
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });
  client.use(authMiddleware);
  return client;
}

export const api = createApiClient();
