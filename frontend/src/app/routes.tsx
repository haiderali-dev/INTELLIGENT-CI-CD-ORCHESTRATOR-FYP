import type { ComponentType } from "react";
import type { RouteObject } from "react-router";

import { AppShell } from "@/app/shell/AppShell";
import { NAV_ITEMS, type NavItem } from "@/app/shell/nav";
import { SIGN_IN_PATH } from "@/auth/next";
import { RequireSession } from "@/auth/RequireSession";
import { AdminPage } from "@/pages/AdminPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { AssistantPage } from "@/pages/AssistantPage";
import { CatalogPage } from "@/pages/CatalogPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { QueuePage } from "@/pages/QueuePage";
import { RunsPage } from "@/pages/RunsPage";
import { SignInPage } from "@/pages/SignInPage";
import type { AssistantKind } from "@/workspace/assistants";

const ASSISTANT_PATH = /^\/assistants\/(freestyle|pipeline)$/;

type Page = ComponentType<{ item: Pick<NavItem, "label" | "description"> }>;

/** Each sidebar entry's page, by its address (the assistants are routed on their own below). */
function pageFor(to: string): Page {
  switch (to) {
    case "/queue":
      return QueuePage;
    case "/runs":
      return RunsPage;
    case "/analytics":
      return AnalyticsPage;
    case "/catalog":
      return CatalogPage;
    case "/admin":
      return AdminPage;
    default:
      throw new Error(`no page for ${to}`);
  }
}

function routeFor(item: NavItem): RouteObject {
  if (item.to === "/") {
    return { index: true, element: <OverviewPage item={item} /> };
  }
  const assistant = ASSISTANT_PATH.exec(item.to)?.[1] as AssistantKind | undefined;
  if (assistant) {
    // The open chat is in the address, so a reload or a shared link keeps it (T6.5).
    return { path: `${item.to}/:chatId?`, element: <AssistantPage assistant={assistant} /> };
  }
  const Page = pageFor(item.to);
  return { path: item.to, element: <Page item={item} /> };
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
