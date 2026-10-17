/**
 * A stand-in for the backend's HTTP API, for tests: routes by "METHOD /path", records every
 * request, and answers with the backend's own shapes. The types come from the generated schema,
 * so a fake answer that drifts from the real API fails to compile.
 */

import { createApiClient, type ErrorCode } from "@/api/client";
import type { components } from "@/api/schema";
import { Session } from "@/auth/session";

type Tokens = components["schemas"]["TokenResponse"];
type User = components["schemas"]["UserResponse"];
type Handler = (request: Request) => Response | Promise<Response>;

export const BASE_URL = "http://backend.test";
export const PASSWORD = "correct horse battery staple";

export const DEVELOPER: User = {
  id: "user-1",
  email: "dev@example.com",
  role: "DEVELOPER",
  active: true,
};

export const ADMIN: User = {
  id: "user-9",
  email: "admin@example.com",
  role: "ADMIN",
  active: true,
};

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function apiError(
  status: number,
  code: ErrorCode,
  message: string,
  details: Record<string, unknown> = {},
): Response {
  return json(status, { error: { code, message, details } });
}

/** What fetch does when nothing answers. */
export function noAnswer(): never {
  throw new TypeError("Failed to fetch");
}

/** "GET /api/conversations/:id" as a pattern: a `:name` segment matches any one path segment. */
function routePattern(route: string): RegExp {
  const escaped = route
    .split("/")
    .map((segment) =>
      segment.startsWith(":") ? "[^/]+" : segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
    )
    .join("/");
  return new RegExp(`^${escaped}$`);
}

export class FakeBackend {
  /** Every request, cloned so a test can still read its body. */
  readonly requests: Request[] = [];
  private readonly routes = new Map<string, { pattern: RegExp; handler: Handler }>();
  private issued = 0;

  /** Answers `route`, such as "POST /api/auth/login" or "GET /api/pipelines/:id". A later
   * handler for the same route replaces the earlier one. */
  on(route: string, handler: Handler): this {
    this.routes.delete(route);
    this.routes.set(route, { pattern: routePattern(route), handler });
    return this;
  }

  /** A token pair as the backend sends it, with new token strings each time: access-1,
   * refresh-1, then access-2, refresh-2, and so on. */
  tokens(user: User = DEVELOPER, expiresInSeconds = 900): Tokens {
    this.issued += 1;
    return {
      access_token: `access-${this.issued}`,
      refresh_token: `refresh-${this.issued}`,
      token_type: "bearer",
      expires_in_seconds: expiresInSeconds,
      user,
    };
  }

  readonly fetch = async (request: Request): Promise<Response> => {
    this.requests.push(request.clone());
    const route = `${request.method} ${new URL(request.url).pathname}`;
    // The newest matching route wins, so a test can override a general one.
    const match = [...this.routes.values()].reverse().find(({ pattern }) => pattern.test(route));
    const response = await (match
      ? match.handler(request)
      : apiError(404, "BAD_REQUEST", `No fake route for ${route}.`));
    return response;
  };

  /** The requests a route received, in order. The route may be a pattern. */
  calls(route: string): Request[] {
    const pattern = routePattern(route);
    return this.requests.filter((request) =>
      pattern.test(`${request.method} ${new URL(request.url).pathname}`),
    );
  }
}

/** A backend whose auth endpoints behave like the real ones for one user. */
export function authBackend(user: User = DEVELOPER): FakeBackend {
  const backend = new FakeBackend();
  return backend
    .on("POST /api/auth/login", () => json(200, backend.tokens(user)))
    .on("POST /api/auth/refresh", () => json(200, backend.tokens(user)))
    .on("POST /api/auth/logout", () => new Response(null, { status: 204 }));
}

export function makeSession(backend: FakeBackend): Session {
  return new Session({
    client: createApiClient({ baseUrl: BASE_URL, fetch: backend.fetch }),
    storage: window.sessionStorage,
  });
}

/** A session already signed in, for pages behind <RequireSession>. */
export async function signedInSession(
  user: User = DEVELOPER,
): Promise<{ backend: FakeBackend; session: Session }> {
  const backend = authBackend(user);
  const session = makeSession(backend);
  await session.signIn(user.email, PASSWORD);
  return { backend, session };
}

/** The JSON body a recorded request sent. */
export async function bodyOf(request: Request | undefined): Promise<unknown> {
  if (!request) {
    throw new Error("no such request was sent");
  }
  return request.clone().json();
}
