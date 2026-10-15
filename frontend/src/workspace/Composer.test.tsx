import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { AssistantKind } from "./assistants";
import { Composer } from "./Composer";

const SERVICES = ["payment-service", "auth-service"];

/** The composer as a page holds it: the page owns the draft. */
function Harness({
  initial = "",
  waiting = false,
  assistant = "freestyle",
  onSend = vi.fn(),
  onStop = vi.fn(),
}: {
  initial?: string;
  waiting?: boolean;
  assistant?: AssistantKind;
  onSend?: (text: string) => void;
  onStop?: () => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <Composer
      assistant={assistant}
      value={value}
      onChange={setValue}
      onSend={(text) => {
        onSend(text);
        setValue("");
      }}
      waiting={waiting}
      onStop={onStop}
      services={SERVICES}
    />
  );
}

const box = () => screen.getByRole("textbox");

describe("Composer", () => {
  it("has each assistant's own placeholder and name", () => {
    const { rerender } = render(<Harness />);
    expect(screen.getByRole("textbox", { name: "Message the Freestyle Assistant" })).toHaveAttribute(
      "placeholder",
      "Message the Freestyle Assistant",
    );

    rerender(<Harness assistant="pipeline" />);
    expect(screen.getByRole("textbox", { name: "Message the Pipeline Assistant" })).toBeInTheDocument();
  });

  it("sends on Enter, trimmed, and adds a line on Shift+Enter", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);

    await user.type(box(), "  Build payment-service{Shift>}{Enter}{/Shift}from main ");
    expect(box()).toHaveValue("  Build payment-service\nfrom main ");

    await user.keyboard("{Enter}");
    expect(onSend).toHaveBeenCalledWith("Build payment-service\nfrom main");
    expect(box()).toHaveValue("");
  });

  it("sends nothing when there is nothing to send", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);

    await user.type(box(), "   {Enter}");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend).not.toHaveBeenCalled();
  });

  it("completes service names from the keyboard", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(box(), "Deploy pay");

    const option = screen.getByRole("option", { name: "payment-service" });
    expect(option).toHaveAttribute("aria-selected", "true");
    expect(box()).toHaveAttribute("aria-activedescendant", option.id);
    expect(screen.getByText(/1 suggestion\. Up and down arrows choose/)).toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(box()).toHaveValue("Deploy payment-service ");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("offers the slash commands with what they stand for, and moves through them", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(box(), "/");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "/statusShow the status of my last run",
      "/rerunRerun my last failed tests",
      "/helpWhat this assistant can do",
    ]);

    await user.keyboard("{ArrowDown}{Tab}");
    expect(box()).toHaveValue("/rerun ");
  });

  it("closes the list on Escape until the text changes", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(box(), "Deploy au");
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();

    await user.keyboard("t");
    expect(screen.getByRole("option", { name: "auth-service" })).toBeInTheDocument();
  });

  it("offers Stop while waiting, and keeps typing but not sending", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(<Harness waiting onSend={onSend} onStop={onStop} />);

    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    await user.type(box(), "staging{Enter}");
    expect(box()).toHaveValue("staging");
    expect(onSend).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("says how much room is left near the backend's limit", () => {
    render(<Harness initial={"x".repeat(3850)} />);

    expect(screen.getByText("150 characters left")).toBeInTheDocument();
    expect(box()).toHaveAttribute("maxlength", "4000");
  });
});
