import { vi } from "vitest";

import type { Session, User } from "@/auth/session";

import { DEVELOPER, signedInSession, type FakeBackend } from "./backend";

const sessions: Session[] = [];

/** A fresh fake backend with `user` signed in. `disposeSessions` ends them after each test. */
export async function signedIn(
  user: User = DEVELOPER,
): Promise<{ backend: FakeBackend; session: Session }> {
  const signed = await signedInSession(user);
  sessions.push(signed.session);
  return signed;
}

export function disposeSessions(): void {
  for (const session of sessions.splice(0)) {
    session.dispose();
  }
  vi.unstubAllGlobals();
}

/** An answer that never comes, to see a page while it waits. */
export function neverAnswers(): Promise<Response> {
  return new Promise<Response>(() => undefined);
}

/** A screen narrower than 768 px: every media query in the app answers no. */
export function narrowScreen(): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
}
