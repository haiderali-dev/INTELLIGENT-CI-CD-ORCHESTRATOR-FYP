import type { RouteObject } from "react-router";

import { AppShell } from "@/app/shell/AppShell";
import { NAV_ITEMS } from "@/app/shell/nav";
import { SIGN_IN_PATH } from "@/auth/next";
import { RequireSession } from "@/auth/RequireSession";
import { AssistantPage } from "@/pages/AssistantPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";
import { QueuePage } from "@/pages/QueuePage";
import { SignInPage } from "@/pages/SignInPage";
import type { AssistantKind } from "@/workspace/assistants";

const ASSISTANT_PATH = /^\/assistants\/(freestyle|pipeline)$/;

function routeFor(item: (typeof NAV_ITEMS)[number]): RouteObject {
  if (item.to === "/") {
    return { index: true, element: <PlaceholderPage item={item} /> };
  }
  const assistant = ASSISTANT_PATH.exec(item.to)?.[1] as AssistantKind | undefined;
  if (assistant) {
    // The open chat is in the address, so a reload or a shared link keeps it (T6.5).
    return { path: `${item.to}/:chatId?`, element: <AssistantPage assistant={assistant} /> };
  }
  if (item.to === "/queue") {
    return { path: item.to, element: <QueuePage item={item} /> };
  }
  return { path: item.to, element: <PlaceholderPage item={item} /> };
}

/** Every route. Sign in sits outside the shell; everything else is inside it, behind a session. */
export const routes: RouteObject[] = [
  { path: SIGN_IN_PATH, element: <SignInPage /> },
  {
    element: (
      <RequireSession>
        <AppShell />
      </RequireSession>
    ),
    children: [...NAV_ITEMS.map(routeFor), { path: "*", element: <NotFoundPage /> }],
  },
];
