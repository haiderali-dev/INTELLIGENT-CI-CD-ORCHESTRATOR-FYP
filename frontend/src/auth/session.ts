/**
 * The signed-in session (T6.3, D-054), against the backend's 4.4.4 endpoints: `POST
 * /api/auth/login`, `/refresh` and `/logout`. It knows nothing of React, so the API client, the
 * live-events client and the pages can share it, and tests can drive it without rendering.
 *
 * - **The access token** is in memory only (src/api/client.ts). It lasts 15 minutes and is renewed
 *   a minute before it expires, and again whenever a request comes back 401.
 * - **The refresh token** is in sessionStorage, so a reload keeps you signed in and closing the tab
 *   signs you out. Every refresh rotates it: the backend revokes the one it was given.
 * - **Refreshes are single-flight.** Requests that fail together share one refresh, because once
 *   the first had rotated the token, a second refresh with the old one would be refused.
 * - **The session ends** when the backend refuses the refresh token, and says why, so the sign-in
 *   page can tell the person what happened instead of just appearing.
 */

import { setAccessToken, type ApiClient } from "@/api/client";
import { readFailure, type Failure } from "@/api/errors";
import type { components } from "@/api/schema";

export type User = components["schemas"]["UserResponse"];
type Tokens = components["schemas"]["TokenResponse"];

/** Why there is no session. Shown on the sign-in page; null when there never was one. */
export type SignedOutReason = "signed-out" | "expired" | "disabled" | "unreachable";

export type SessionState =
  | { status: "restoring" }
  | { status: "signed-in"; user: User }
  | { status: "signed-out"; reason: SignedOutReason | null };

export type SignInResult = { ok: true; user: User } | { ok: false; failure: Failure };

export const REFRESH_TOKEN_KEY = "orchestrator.session";

/** Renew the access token this long before it expires. */
const RENEW_BEFORE_MS = 60_000;
/** After a renewal that got no answer, try again this much later. */
const RENEW_RETRY_MS = 30_000;
const MIN_RENEW_DELAY_MS = 5_000;

type Exchange = "ok" | "refused" | "no-answer";

export interface SessionOptions {
  client: ApiClient;
  /** Where the refresh token is kept. Null keeps it for this page only. */
  storage: Storage | null;
}

/** The tab's sessionStorage, or null where storage is blocked. */
export function browserSessionStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function sameUser(a: User, b: User): boolean {
  return a.id === b.id && a.email === b.email && a.role === b.role && a.active === b.active;
}

export class Session {
  private state: SessionState;
  private refreshToken: string | null;
  private inflight: Promise<Exchange> | null = null;
  private renewTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly listeners = new Set<() => void>();

  constructor(private readonly options: SessionOptions) {
    this.refreshToken = this.readStored();
    this.state = this.refreshToken
      ? { status: "restoring" }
      : { status: "signed-out", reason: null };
  }

  getState = (): SessionState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** On load: trade a stored refresh token for a session. Calling it again changes nothing. */
  async restore(): Promise<void> {
    if (this.state.status !== "restoring") {
      return;
    }
    // "ok" and "refused" have already set the state. With no answer, the token is kept: it may be
    // perfectly good once the server answers, and a reload will try it again.
    if ((await this.exchange()) === "no-answer") {
      this.setState({ status: "signed-out", reason: "unreachable" });
    }
  }

  async signIn(email: string, password: string): Promise<SignInResult> {
    let result;
    try {
      result = await this.options.client.POST("/api/auth/login", { body: { email, password } });
    } catch {
      return { ok: false, failure: { kind: "unreachable" } };
    }
    if (!result.data) {
      return { ok: false, failure: readFailure(result.response, result.error) };
    }
    this.begin(result.data);
    return { ok: true, user: result.data.user };
  }

  /**
   * A new access token. Resolves true when one is in place. Ends the session when the backend
   * refuses the refresh token; leaves it alone when the backend did not answer.
   */
  async refresh(): Promise<boolean> {
    if (this.state.status === "signed-out") {
      return false;
    }
    return (await this.exchange()) === "ok";
  }

  /** Revokes the refresh token on the server, then forgets both tokens whatever the answer. */
  async signOut(): Promise<void> {
    this.clearRenew();
    if (this.state.status === "signed-in") {
      try {
        let { response } = await this.logout();
        // An access token that expired while the laptop slept: renew it, then sign out properly,
        // so the refresh token does not outlive the session on the server.
        if (response.status === 401 && (await this.exchange()) === "ok") {
          ({ response } = await this.logout());
        }
      } catch {
        // The server did not answer. The tokens are forgotten here regardless.
      }
    }
    this.end("signed-out");
  }

  /** Stops the renewal timer. For tests; the app's session lives as long as the page. */
  dispose(): void {
    this.clearRenew();
    this.listeners.clear();
  }

  private logout() {
    return this.options.client.POST("/api/auth/logout", {
      body: { refresh_token: this.refreshToken },
    });
  }

  private exchange(): Promise<Exchange> {
    this.inflight ??= this.runExchange().finally(() => {
      this.inflight = null;
    });
    return this.inflight;
  }

  private async runExchange(): Promise<Exchange> {
    const token = this.refreshToken;
    if (!token) {
      this.end("expired");
      return "refused";
    }

    let result;
    try {
      result = await this.options.client.POST("/api/auth/refresh", {
        body: { refresh_token: token },
      });
    } catch {
      this.renewLater();
      return "no-answer";
    }
    if (result.data) {
      this.begin(result.data);
      return "ok";
    }

    const failure = readFailure(result.response, result.error);
    const { status } = result.response;
    // A 4xx other than "slow down" is a verdict on the token itself. Anything else is the server
    // having a bad moment, which is no reason to throw the person out.
    if (failure.kind === "api" && status >= 400 && status < 500 && status !== 429) {
      this.end(failure.error.code === "ACCOUNT_DISABLED" ? "disabled" : "expired");
      return "refused";
    }
    this.renewLater();
    return "no-answer";
  }

  private begin(tokens: Tokens): void {
    this.refreshToken = tokens.refresh_token;
    this.writeStored(tokens.refresh_token);
    setAccessToken(tokens.access_token);
    this.scheduleRenew(tokens.expires_in_seconds * 1000 - RENEW_BEFORE_MS);

    // A renewal usually returns the same person. Keeping the same state object then spares every
    // subscriber a render; a changed role or address still comes through.
    const current = this.state;
    if (current.status !== "signed-in" || !sameUser(current.user, tokens.user)) {
      this.setState({ status: "signed-in", user: tokens.user });
    }
  }

  private end(reason: SignedOutReason): void {
    this.clearRenew();
    this.refreshToken = null;
    this.writeStored(null);
    setAccessToken(null);
    this.setState({ status: "signed-out", reason });
  }

  private scheduleRenew(delayMs: number): void {
    this.clearRenew();
    this.renewTimer = setTimeout(
      () => {
        void this.refresh();
      },
      Math.max(MIN_RENEW_DELAY_MS, delayMs),
    );
  }

  private renewLater(): void {
    if (this.state.status === "signed-in") {
      this.scheduleRenew(RENEW_RETRY_MS);
    }
  }

  private clearRenew(): void {
    clearTimeout(this.renewTimer);
    this.renewTimer = undefined;
  }

  private setState(state: SessionState): void {
    this.state = state;
    for (const listener of this.listeners) {
      listener();
    }
  }

  private readStored(): string | null {
    try {
      return this.options.storage?.getItem(REFRESH_TOKEN_KEY) ?? null;
    } catch {
      return null;
    }
  }

  private writeStored(token: string | null): void {
    try {
      if (token) {
        this.options.storage?.setItem(REFRESH_TOKEN_KEY, token);
      } else {
        this.options.storage?.removeItem(REFRESH_TOKEN_KEY);
      }
    } catch {
      // Blocked storage: the session lasts for this page only.
    }
  }
}
