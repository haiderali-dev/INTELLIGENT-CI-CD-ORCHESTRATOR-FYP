import { useState } from "react";

import { ROLE_LABEL } from "@/auth/roles";
import { useSession, useSessionClient } from "@/auth/sessionContext";

/** Who is signed in, and the way out (DESIGN.md section 4: the sidebar's footer says who). */
export function SignedInAs() {
  const state = useSession();
  const session = useSessionClient();
  const [signingOut, setSigningOut] = useState(false);

  // In the moment between the session ending and the router leaving the shell, there is no one.
  if (state.status !== "signed-in") {
    return null;
  }
  const { user } = state;

  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="min-w-0">
        <span className="block text-graphite">Signed in as</span>
        <span className="block truncate font-semibold" title={user.email}>
          {user.email}
        </span>
        <span className="block text-graphite">{ROLE_LABEL[user.role]}</span>
      </p>
      <button
        type="button"
        aria-disabled={signingOut}
        onClick={() => {
          if (signingOut) {
            return;
          }
          setSigningOut(true);
          // The session ends whatever the server says, and the router then leaves the shell.
          void session.signOut();
        }}
        className="self-start rounded-control border border-graphite px-3 py-1 text-sm aria-disabled:cursor-progress max-md:min-h-11"
      >
        {signingOut ? "Signing out" : "Sign out"}
      </button>
    </div>
  );
}
