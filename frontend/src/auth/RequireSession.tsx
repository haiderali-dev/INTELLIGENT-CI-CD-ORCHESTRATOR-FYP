import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { signInPath } from "./next";
import { RestoringSession } from "./RestoringSession";
import { useSession } from "./sessionContext";

/**
 * Everything inside the shell needs a session. Without one, the person is sent to sign in, and
 * back to the page they asked for afterwards. After signing out on purpose they are not sent back:
 * whoever signs in next may be someone else.
 */
export function RequireSession({ children }: { children: ReactNode }) {
  const state = useSession();
  const location = useLocation();

  if (state.status === "restoring") {
    return <RestoringSession />;
  }
  if (state.status === "signed-out") {
    const here = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={signInPath(state.reason === "signed-out" ? null : here)} replace />;
  }
  return children;
}
