import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { MEDIUM_QUERY, WIDE_QUERY } from "@/lib/useMediaQuery";

import { WorkspaceLayout } from "./WorkspaceLayout";

/** Pretend the window is a given width: wide is 1280 px and up, medium 768 px and up. */
function windowWidth(width: "wide" | "medium" | "narrow") {
  const matches: Record<string, boolean> = {
    [WIDE_QUERY]: width === "wide",
    [MEDIUM_QUERY]: width !== "narrow",
  };
  window.matchMedia = (query: string) =>
    ({
      matches: matches[query] ?? false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }) as unknown as MediaQueryList;
}

afterEach(() => {
  // jsdom has no matchMedia of its own.
  Reflect.deleteProperty(window, "matchMedia");
});

function renderLayout(activeChatId: string | null = "chat-1") {
  return render(
    <WorkspaceLayout
      assistant="freestyle"
      activeChatId={activeChatId}
      chats={<p>Chat list</p>}
      thread={<p>The thread</p>}
      composer={<p>The composer</p>}
      preview={<p>The preview</p>}
      previewSummary="Preview: 3 jobs, all checks pass"
    />,
  );
}

describe("WorkspaceLayout", () => {
  it("puts chats, thread and preview side by side from 1280 px", () => {
    windowWidth("wide");
    renderLayout();

    expect(screen.getByRole("heading", { level: 1, name: "Freestyle Assistant" })).toBeInTheDocument();
    expect(within(screen.getByRole("complementary", { name: "Chats" })).getByText("Chat list")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Conversation" })).getByText("The thread")).toBeInTheDocument();
    expect(within(screen.getByRole("complementary", { name: "Preview" })).getByText("The preview")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Chats" })).toBeNull();
  });

  it("gives the page its assistant's accent", () => {
    windowWidth("wide");
    renderLayout();

    const heading = screen.getByRole("heading", { level: 1, name: "Freestyle Assistant" });
    expect(heading.closest("header")).toHaveClass("border-l-spruce");
  });

  it("makes the preview a drawer under 1280 px", async () => {
    const user = userEvent.setup();
    windowWidth("medium");
    renderLayout();

    expect(screen.queryByText("The preview")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Preview" }));

    const drawer = await screen.findByRole("dialog", { name: "Preview" });
    expect(within(drawer).getByText("The preview")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "Close preview" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("makes it a bottom sheet under 768 px, with a one-line summary to open it", async () => {
    const user = userEvent.setup();
    windowWidth("narrow");
    renderLayout();

    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Preview: 3 jobs, all checks pass" }));

    expect(within(await screen.findByRole("dialog", { name: "Preview" })).getByText("The preview")).toBeInTheDocument();
  });

  it("closes the chats sheet when another chat is chosen", async () => {
    const user = userEvent.setup();
    windowWidth("narrow");
    const { rerender } = renderLayout("chat-1");

    await user.click(screen.getByRole("button", { name: "Chats" }));
    expect(within(await screen.findByRole("dialog", { name: "Chats" })).getByText("Chat list")).toBeInTheDocument();

    rerender(
      <WorkspaceLayout
        assistant="freestyle"
        activeChatId="chat-2"
        chats={<p>Chat list</p>}
        thread={<p>The thread</p>}
        composer={<p>The composer</p>}
        preview={<p>The preview</p>}
        previewSummary="Preview: nothing yet"
      />,
    );
    expect(screen.queryByRole("dialog", { name: "Chats" })).toBeNull();
  });
});
