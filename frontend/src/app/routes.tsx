import type { RouteObject } from "react-router";

import { AppShell } from "@/app/shell/AppShell";
import { NAV_ITEMS } from "@/app/shell/nav";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const SIGN_IN = {
  label: "Sign in",
  description: "Sign in with the email and password your administrator gave you.",
  task: "T6.3",
};

/** Every route. Sign in sits outside the shell; everything else inside it. */
export const routes: RouteObject[] = [
  { path: "/sign-in", element: <PlaceholderPage item={SIGN_IN} /> },
  {
    element: <AppShell />,
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
