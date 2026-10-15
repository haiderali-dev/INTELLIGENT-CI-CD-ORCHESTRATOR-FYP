import { createContext, useContext, useSyncExternalStore } from "react";

import type { Session, SessionState } from "./session";

export const SessionContext = createContext<Session | null>(null);

/** The session itself, for signing in and out. */
export function useSessionClient(): Session {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("the session needs a <SessionProvider> above it");
  }
  return session;
}

/** The session's state, re-rendering when it changes. */
export function useSession(): SessionState {
  const session = useSessionClient();
  return useSyncExternalStore(session.subscribe, session.getState, session.getState);
}
