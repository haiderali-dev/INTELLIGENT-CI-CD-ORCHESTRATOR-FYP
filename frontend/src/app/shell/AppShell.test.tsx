import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { routes } from "@/app/routes";
import { THEME_STORAGE_KEY } from "@/app/theme/theme";
import { ThemeProvider } from "@/app/theme/ThemeProvider";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>,
  );
}

const mainNav = () => screen.getByRole("navigation", { name: "Main" });

describe("app shell", () => {
  it("names every page, with the two assistants as separate entries", () => {
    renderAt("/");

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

  it("marks the page you are on", () => {
    renderAt("/queue");

    expect(within(mainNav()).getByRole("link", { name: "Queue" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(mainNav()).getByRole("link", { name: "Overview" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("heading", { level: 1, name: "Queue" })).toBeInTheDocument();
  });

  it("says Staging, so nobody in the room has to wonder", () => {
    renderAt("/");

    expect(screen.getAllByText("Staging").length).toBeGreaterThan(0);
  });

  it("gives each assistant's header its own accent", () => {
    renderAt("/assistants/pipeline");

    const heading = screen.getByRole("heading", { level: 1, name: "Pipeline Assistant" });
    expect(heading.closest("header")).toHaveClass("border-l-plum");
    expect(heading.closest("header")).not.toHaveClass("border-l-spruce");
  });

  it("switches theme with the keyboard or the mouse, and remembers it", async () => {
    const user = userEvent.setup();
    renderAt("/");

    await user.click(screen.getByRole("radio", { name: "Dark" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
  });

  it("offers a way on from an unknown address", () => {
    renderAt("/no-such-page");

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the overview" })).toHaveAttribute("href", "/");
  });

  it("starts with a link that skips to the content", () => {
    renderAt("/");

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });
});
