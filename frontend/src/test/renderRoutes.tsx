import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { routes } from "@/app/routes";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import type { Session } from "@/auth/session";
import { SessionProvider } from "@/auth/SessionProvider";

/** The whole route tree at `path`, as the app renders it, around the given session. */
export function renderRoutes(path: string, session: Session) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <ThemeProvider>
      <SessionProvider session={session}>
        <RouterProvider router={router} />
      </SessionProvider>
    </ThemeProvider>,
  );
  return { router, ...view };
}

/** Where the router is now, as one string. */
export function currentPath(router: ReturnType<typeof createMemoryRouter>): string {
  const { pathname, search } = router.state.location;
  return `${pathname}${search}`;
}
