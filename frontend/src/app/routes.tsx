import type { ComponentType } from "react";
import type { RouteObject } from "react-router";

import { LoadingApp } from "@/app/LoadingApp";
import { AppShell } from "@/app/shell/AppShell";
import { NAV_ITEMS, type NavItem } from "@/app/shell/nav";
import { SIGN_IN_PATH } from "@/auth/next";
import { RequireSession } from "@/auth/RequireSession";
import { NotFoundPage } from "@/pages/NotFoundPage";
import type { AssistantKind } from "@/workspace/assistants";

const ASSISTANT_PATH = /^\/assistants\/(freestyle|pipeline)$/;

type Page = ComponentType<{ item: Pick<NavItem, "label" | "description"> }>;

/**
 * Each sidebar entry's page, by its address, loaded when it is first opened. Every page in one
 * bundle made the first download 745 kB (D-063); each now arrives as its own chunk. Sign in is
 * loaded the same way: its form libraries (zod, react-hook-form) are a fifth of the main bundle,
 * and the Admin page is their only other user.
 */
function loadPage(to: string): () => Promise<Page> {
  switch (to) {
    case "/":
      return () => import("@/pages/OverviewPage").then((module) => module.OverviewPage);
    case "/queue":
      return () => import("@/pages/QueuePage").then((module) => module.QueuePage);
    case "/runs":
      return () => import("@/pages/RunsPage").then((module) => module.RunsPage);
    case "/analytics":
      return () => import("@/pages/AnalyticsPage").then((module) => module.AnalyticsPage);
    case "/catalog":
      return () => import("@/pages/CatalogPage").then((module) => module.CatalogPage);
    case "/admin":
      return () => import("@/pages/AdminPage").then((module) => module.AdminPage);
    default:
      throw new Error(`no page for ${to}`);
  }
}

/**
 * A route whose page is fetched on first navigation. React Router waits for it before changing the
 * address, so the previous page stays on screen until the next one can draw: no empty frame.
 */
function routeFor(item: NavItem): RouteObject {
  const assistant = ASSISTANT_PATH.exec(item.to)?.[1] as AssistantKind | undefined;
  if (assistant) {
    // The open chat is in the address, so a reload or a shared link keeps it (T6.5).
    return {
      path: `${item.to}/:chatId?`,
      lazy: async () => {
        const { AssistantPage } = await import("@/pages/AssistantPage");
        return { element: <AssistantPage assistant={assistant} /> };
      },
    };
  }
  const load = loadPage(item.to);
  const lazy = async () => {
    const Page = await load();
    return { element: <Page item={item} /> };
  };
  return item.to === "/" ? { index: true, lazy } : { path: item.to, lazy };
}

/**
 * Every route. Sign in sits outside the shell; everything else is inside it, behind a session.
 * Both show LoadingApp on the first load until the page asked for has arrived.
 */
export const routes: RouteObject[] = [
  {
    path: SIGN_IN_PATH,
    hydrateFallbackElement: <LoadingApp />,
    lazy: async () => {
      const { SignInPage } = await import("@/pages/SignInPage");
      return { element: <SignInPage /> };
    },
  },
  {
    hydrateFallbackElement: <LoadingApp />,
    element: (
      <RequireSession>
        <AppShell />
      </RequireSession>
    ),
    children: [...NAV_ITEMS.map(routeFor), { path: "*", element: <NotFoundPage /> }],
  },
];
