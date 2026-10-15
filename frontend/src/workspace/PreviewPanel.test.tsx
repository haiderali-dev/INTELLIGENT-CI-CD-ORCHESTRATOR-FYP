import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/toast/ToastProvider";

import type { AssistantKind } from "./assistants";
import { PreviewPanel, type PreviewPlan } from "./PreviewPanel";

const SPEC = "version: 1\nservice: payment-service\nbranch: main\n";

function plan(overrides: Partial<PreviewPlan> = {}): PreviewPlan {
  return {
    spec: { yaml: SPEC, onChange: vi.fn(), edited: false, onRegenerate: vi.fn() },
    artifacts: [
      { name: "fs-payment-service-build", text: "<project><description>build</description></project>" },
      { name: "fs-payment-service-test", text: "<project><description>test</description></project>" },
    ],
    progress: [
      { step: "Understood", ok: true, detail: "build payment-service from main" },
      { step: "Planned", ok: true, detail: "default plan, 0 repair(s)" },
      { step: "Rendered", ok: true, detail: "2 job(s)" },
      { step: "Validated", ok: true, detail: "all checks passed" },
    ],
    checks: [{ name: "schema", label: "Spec schema", status: "passed", message: "", cause: null }],
    explanation: { text: null, loading: false, onExplain: vi.fn() },
    approval: {
      summary: "Creates 2 jobs and starts fs-payment-service-build on main at MEDIUM priority.",
      ready: true,
      onApprove: vi.fn(() => Promise.resolve({ ok: true as const })),
    },
    ...overrides,
  };
}

function renderPreview(assistant: AssistantKind, value: PreviewPlan | null) {
  render(
    <ToastProvider>
      <PreviewPanel assistant={assistant} plan={value} />
    </ToastProvider>,
  );
}

const tabs = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

// The panel loads CodeMirror lazily. Loading it once here makes that load instant in the tests,
// which otherwise depends on how busy the machine is (it timed out once in a full parallel run).
beforeAll(async () => {
  await import("@/components/code/CodeView");
});

describe("PreviewPanel", () => {
  it("invites the next step before there is anything to show", () => {
    renderPreview("freestyle", null);

    expect(
      screen.getByText("Nothing to preview yet. Ask for a build, test or deploy, then choose Generate."),
    ).toBeInTheDocument();
  });

  it("shows config.xml for freestyle and the Jenkinsfile for Pipeline", () => {
    renderPreview("freestyle", plan());
    expect(tabs()).toEqual(["Spec", "Config", "Checks", "Explanation"]);
  });

  it("names the Pipeline's artifact the Jenkinsfile", () => {
    renderPreview("pipeline", plan({ artifacts: [{ name: "pl-payment-service", text: "pipeline {}" }] }));
    expect(tabs()).toEqual(["Spec", "Jenkinsfile", "Checks", "Explanation"]);
  });

  it("opens on the spec, editable, with Approve and run below the tabs", async () => {
    renderPreview("freestyle", plan());

    const spec = await screen.findByRole("textbox", { name: "Spec" });
    expect(spec).toHaveAttribute("contenteditable", "true");
    expect(spec).toHaveTextContent("service: payment-service");
    expect(
      screen.getByText("Creates 2 jobs and starts fs-payment-service-build on main at MEDIUM priority."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and run" })).toHaveAttribute(
      "aria-disabled",
      "false",
    );
  });

  it("offers to generate again from an edited spec", async () => {
    const user = userEvent.setup();
    const onRegenerate = vi.fn();
    renderPreview(
      "freestyle",
      plan({ spec: { yaml: SPEC, onChange: vi.fn(), edited: true, onRegenerate } }),
    );

    await user.click(screen.getByRole("button", { name: "Generate from this spec" }));
    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("shows each job's config.xml read-only, one job at a time", async () => {
    const user = userEvent.setup();
    renderPreview("freestyle", plan());

    await user.click(screen.getByRole("tab", { name: "Config" }));
    const first = await screen.findByRole("textbox", { name: "config.xml for fs-payment-service-build" });
    expect(first).toHaveAttribute("aria-readonly", "true");

    await user.selectOptions(screen.getByLabelText("Job"), "fs-payment-service-test");
    expect(
      await screen.findByRole("textbox", { name: "config.xml for fs-payment-service-test" }),
    ).toHaveTextContent("test");
  });

  it("puts the progress line and the checklist under Checks", async () => {
    const user = userEvent.setup();
    renderPreview("freestyle", plan());

    await user.click(screen.getByRole("tab", { name: "Checks" }));

    const panel = screen.getByRole("tabpanel", { name: "Checks" });
    expect(within(panel).getByRole("list", { name: "Progress" })).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "Checks" })).toHaveTextContent("Spec schema: Passed");
  });

  it("explains the plan on request, and shows the words as they arrive", async () => {
    const user = userEvent.setup();
    const onExplain = vi.fn();
    renderPreview("freestyle", plan({ explanation: { text: null, loading: false, onExplain } }));

    await user.click(screen.getByRole("tab", { name: "Explanation" }));
    await user.click(screen.getByRole("button", { name: "Explain this plan" }));
    expect(onExplain).toHaveBeenCalledOnce();
  });

  it("says when the explanation is still being written", async () => {
    const user = userEvent.setup();
    renderPreview(
      "freestyle",
      plan({ explanation: { text: "This builds payment-service", loading: true, onExplain: vi.fn() } }),
    );

    await user.click(screen.getByRole("tab", { name: "Explanation" }));
    expect(screen.getByText("This builds payment-service")).toBeInTheDocument();
    expect(screen.getByText("Still writing")).toBeInTheDocument();
  });
});
