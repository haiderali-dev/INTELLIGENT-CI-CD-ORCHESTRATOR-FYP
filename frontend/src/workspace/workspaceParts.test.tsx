import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatList } from "./ChatList";
import { EmptyState } from "./EmptyState";
import { FallbackNotice } from "./FallbackNotice";
import { MessageText, Thread, ThreadMessage } from "./Thread";

describe("EmptyState", () => {
  it("says what the assistant creates, offers four commands and names the services", async () => {
    const user = userEvent.setup();
    const onExample = vi.fn();
    render(
      <EmptyState assistant="pipeline" services={["payment-service", "auth-service"]} onExample={onExample} />,
    );

    expect(screen.getByText(/^Creates one Pipeline job on staging/)).toBeInTheDocument();
    const commands = within(screen.getByRole("list")).getAllByRole("button");
    expect(commands).toHaveLength(4);
    expect(screen.getByText("payment-service, auth-service")).toBeInTheDocument();

    await user.click(commands[0] as HTMLElement);
    expect(onExample).toHaveBeenCalledWith(
      "Build, test and deploy the latest commit of payment-service to staging",
    );
  });

  it("is not a dead end when the catalog is empty", () => {
    render(<EmptyState assistant="freestyle" services={[]} onExample={vi.fn()} />);

    expect(screen.getByText("none yet. An administrator adds them to the catalog.")).toBeInTheDocument();
  });
});

describe("ChatList", () => {
  const chats = [
    { id: "a", title: "Deploy payment-service", assistant: "FREESTYLE", created_at: "2026-10-15T09:00:00Z" },
    { id: "b", title: "Rerun tests", assistant: "FREESTYLE", created_at: "2026-10-14T16:30:00Z" },
  ];

  it("lists the chats, marks the open one, and starts a new one", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onNew = vi.fn();
    render(<ChatList chats={chats} activeId="a" onSelect={onSelect} onNew={onNew} />);

    expect(screen.getByRole("button", { name: /Deploy payment-service/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    await user.click(screen.getByRole("button", { name: /Rerun tests/ }));
    expect(onSelect).toHaveBeenCalledWith("b");
    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(onNew).toHaveBeenCalledOnce();
  });

  it("says how to start when there are none", () => {
    render(<ChatList chats={[]} activeId={null} onSelect={vi.fn()} onNew={vi.fn()} />);

    expect(screen.getByText("No chats yet. Your first message starts one.")).toBeInTheDocument();
  });
});

describe("Thread", () => {
  it("announces new messages, and names who said each one", () => {
    render(
      <Thread label="Conversation with the Freestyle Assistant">
        <ThreadMessage author="user" assistant="freestyle">
          <MessageText>Build payment-service from main</MessageText>
        </ThreadMessage>
        <ThreadMessage author="assistant" assistant="freestyle">
          <MessageText>{"Ready to generate: build payment-service.\nGenerate when ready."}</MessageText>
          <FallbackNotice />
        </ThreadMessage>
      </Thread>,
    );

    const thread = screen.getByRole("list", { name: "Conversation with the Freestyle Assistant" });
    expect(thread).toHaveAttribute("aria-live", "polite");
    const [mine, theirs] = within(thread).getAllByRole("listitem");
    expect(mine).toHaveTextContent(/^You/);
    expect(theirs).toHaveTextContent(/^Freestyle Assistant/);
    expect(theirs).toHaveTextContent("The rule parser answered this, because the AI model was not available.");
  });
});
