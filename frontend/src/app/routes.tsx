import type { RouteObject } from "react-router";

import { AppShell } from "@/app/shell/AppShell";
import { NAV_ITEMS } from "@/app/shell/nav";
import { SIGN_IN_PATH } from "@/auth/next";
import { RequireSession } from "@/auth/RequireSession";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";
import { SignInPage } from "@/pages/SignInPage";

/** Every route. Sign in sits outside the shell; everything else is inside it, behind a session. */
export const routes: RouteObject[] = [
  { path: SIGN_IN_PATH, element: <SignInPage /> },
  {
    element: (
      <RequireSession>
        <AppShell />
      </RequireSession>
    ),
    children: [
      ...NAV_ITEMS.map((item): RouteObject =>
        item.to === "/"
          ? { index: true, element: <PlaceholderPage item={item} /> }
          : { path: item.to, element: <PlaceholderPage item={item} /> },
      ),
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
