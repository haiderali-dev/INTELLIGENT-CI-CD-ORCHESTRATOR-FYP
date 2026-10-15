import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/toast/ToastProvider";

import { ApproveAndRun, type ApproveResult } from "./ApproveAndRun";

const SUMMARY =
  "Creates 3 jobs and starts fs-payment-service-build on main at HIGH priority.";

function renderApproval(onApprove: () => Promise<ApproveResult>, ready = true) {
  render(
    <ToastProvider>
      <ApproveAndRun summary={ready ? SUMMARY : null} ready={ready} onApprove={onApprove} />
    </ToastProvider>,
  );
}

describe("ApproveAndRun", () => {
  it("approves with the keyboard alone, says exactly what will happen, then Run started", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn(() => Promise.resolve<ApproveResult>({ ok: true }));
    renderApproval(onApprove);

    await user.tab();
    expect(screen.getByRole("button", { name: "Approve and run" })).toHaveFocus();
    await user.keyboard("{Enter}");

    const dialog = await screen.findByRole("alertdialog", { name: "Approve and run" });
    expect(dialog).toHaveAccessibleDescription(SUMMARY);
    // Focus starts on Cancel, the safe choice; one Tab reaches the action.
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Approve and run" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onApprove).toHaveBeenCalledOnce();
    expect(await screen.findByText("Run started")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("keeps a refusal in the dialog, with what happened and what to do", async () => {
    const user = userEvent.setup();
    renderApproval(() =>
      Promise.resolve<ApproveResult>({
        ok: false,
        failure: {
          kind: "api",
          status: 409,
          error: {
            code: "CHAIN_ALREADY_RUNNING",
            message: "payment-service already has a chain running. Wait for it, or cancel it first.",
            details: {},
          },
        },
      }),
    );

    await user.click(screen.getByRole("button", { name: "Approve and run" }));
    await user.click(screen.getByRole("button", { name: "Approve and run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "payment-service already has a chain running. Wait for it, or cancel it first.",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.queryByText("Run started")).toBeNull();
  });

  it("cannot be approved before every check passes, and says so", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn(() => Promise.resolve<ApproveResult>({ ok: true }));
    renderApproval(onApprove, false);

    const button = screen.getByRole("button", { name: "Approve and run" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription("Available once every check passes.");

    await user.click(button);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onApprove).not.toHaveBeenCalled();
  });
});
