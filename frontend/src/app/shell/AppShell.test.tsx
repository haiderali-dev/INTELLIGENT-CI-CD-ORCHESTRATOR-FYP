import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "@/app/theme/theme";
import { REFRESH_TOKEN_KEY, type Session } from "@/auth/session";
import { ADMIN, apiError, DEVELOPER, signedInSession } from "@/test/backend";
import { currentPath, renderRoutes } from "@/test/renderRoutes";

const sessions: Session[] = [];

afterEach(() => {
  for (const session of sessions.splice(0)) {
    session.dispose();
  }
});

/** The shell at `path`, signed in, once the page has rendered. */
async function renderAt(path: string, user = DEVELOPER) {
  const { backend, session } = await signedInSession(user);
  sessions.push(session);
  const view = renderRoutes(path, session);
  await screen.findByRole("heading", { level: 1 });
  return { backend, session, ...view };
}

const mainNav = () => screen.getByRole("navigation", { name: "Main" });

describe("app shell", () => {
  it("names every page, with the two assistants as separate entries", async () => {
    await renderAt("/", ADMIN);

    const links = within(mainNav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Overview",
      "Freestyle Assistant",
      "Pipeline Assistant",
      "Queue",
      "Jobs and runs",
      "Analytics",
      "Service catalog",
      "Admin",
    ]);
  });

  it("lists Admin only for Admins, since the backend refuses everyone else", async () => {
    await renderAt("/");

    const links = within(mainNav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Overview",
      "Freestyle Assistant",
      "Pipeline Assistant",
      "Queue",
      "Jobs and runs",
      "Analytics",
      "Service catalog",
    ]);
  });

  it("marks the page you are on", async () => {
    await renderAt("/queue");

    expect(within(mainNav()).getByRole("link", { name: "Queue" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(mainNav()).getByRole("link", { name: "Overview" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("heading", { level: 1, name: "Queue" })).toBeInTheDocument();
  });

  it("says Staging, so nobody in the room has to wonder", async () => {
    await renderAt("/");

    expect(screen.getAllByText("Staging").length).toBeGreaterThan(0);
  });

  it("gives each assistant's header its own accent", async () => {
    await renderAt("/assistants/pipeline");

    const heading = screen.getByRole("heading", { level: 1, name: "Pipeline Assistant" });
    expect(heading.closest("header")).toHaveClass("border-l-plum");
    expect(heading.closest("header")).not.toHaveClass("border-l-spruce");
  });

  it("switches theme with the keyboard or the mouse, and remembers it", async () => {
    const user = userEvent.setup();
    await renderAt("/");

    await user.click(screen.getByRole("radio", { name: "Dark" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
  });

  it("offers a way on from an unknown address", async () => {
    await renderAt("/no-such-page");

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the overview" })).toHaveAttribute("href", "/");
  });

  it("starts with a link that skips to the content", async () => {
    await renderAt("/");

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });
});

describe("who is signed in", () => {
  it("names the signed-in person and their role", async () => {
    await renderAt("/", { ...DEVELOPER, email: "ops@example.com", role: "DEVOPS" });

    expect(screen.getByText("Signed in as")).toBeInTheDocument();
    expect(screen.getByText("ops@example.com")).toBeInTheDocument();
    expect(screen.getByText("DevOps")).toBeInTheDocument();
  });

  it("signs out to the sign-in page, which says so and does not offer the last page back", async () => {
    const user = userEvent.setup();
    const { backend, router } = await renderAt("/queue");

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByText("You signed out.")).toBeInTheDocument();
    expect(currentPath(router)).toBe("/sign-in");
    expect(backend.calls("POST /api/auth/logout")).toHaveLength(1);
    expect(window.sessionStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("sends you to sign in, keeping your place, when the session ends while you work", async () => {
    const { backend, session, router } = await renderAt("/runs");
    backend.on("POST /api/auth/refresh", () =>
      apiError(401, "TOKEN_INVALID", "This session is no longer valid."),
    );

    await act(async () => {
      await session.refresh();
    });

    expect(
      await screen.findByText("Your session ended. Sign in again to carry on where you were."),
    ).toBeInTheDocument();
    expect(currentPath(router)).toBe("/sign-in?next=%2Fruns");
  });
});
