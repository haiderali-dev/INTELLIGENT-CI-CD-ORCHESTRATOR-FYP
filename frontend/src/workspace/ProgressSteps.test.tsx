import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ProgressStep } from "./progress";
import { ProgressSteps, ValidationChecklist } from "./ProgressSteps";

const ALL_PASSED: ProgressStep[] = [
  { step: "Understood", ok: true, detail: "deploy payment-service from main to staging" },
  { step: "Planned", ok: true, detail: "model openai/gpt-oss-120b, 0 repair(s)" },
  { step: "Rendered", ok: true, detail: "3 job(s)" },
  { step: "Validated", ok: true, detail: "all checks passed" },
];

const steps = () =>
  within(screen.getByRole("list", { name: "Progress" }))
    .getAllByRole("listitem")
    .map((item) => item.textContent);

describe("ProgressSteps", () => {
  it("shows the four steps in order, each with how it went", () => {
    render(<ProgressSteps steps={ALL_PASSED} />);

    expect(steps()).toEqual([
      "Understooddeploy payment-service from main to staging",
      "Plannedmodel openai/gpt-oss-120b, 0 repair(s)",
      "Rendered3 job(s)",
      "Validatedall checks passed",
    ]);
    expect(screen.getByText("Validated", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("shows the exact error, and the steps after it as not reached", () => {
    const error = "XML well-formedness: line 12: mismatched tag";
    render(
      <ProgressSteps
        steps={[
          ALL_PASSED[0] as ProgressStep,
          ALL_PASSED[1] as ProgressStep,
          { step: "Rendered", ok: false, detail: error },
        ]}
      />,
    );

    expect(steps()).toEqual([
      "Understooddeploy payment-service from main to staging",
      "Plannedmodel openai/gpt-oss-120b, 0 repair(s)",
      `Rendered failed${error}`,
      "Validated, not reached",
    ]);
    expect(
      screen.getByText(`Rendered failed: ${error}`, { selector: "[aria-live]" }),
    ).toBeInTheDocument();
  });

  it("keeps state colours off steps that are not builds", () => {
    const { container } = render(<ProgressSteps steps={ALL_PASSED} />);

    expect(container.innerHTML).not.toMatch(/text-state-/);
  });
});

describe("ValidationChecklist", () => {
  it("gives each check its result as a word, and the reason when it did not pass", () => {
    render(
      <ValidationChecklist
        checks={[
          { name: "schema", label: "Spec schema", status: "passed", message: "", cause: null },
          {
            name: "catalog",
            label: "Catalog",
            status: "warning",
            message: "Branch is not the default.",
            cause: "input",
          },
          {
            name: "production",
            label: "No production",
            status: "failed",
            message: "The spec names production. Staging is the only environment.",
            cause: "input",
          },
        ]}
      />,
    );

    const items = within(screen.getByRole("list", { name: "Checks" })).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Spec schema: Passed",
      "Catalog: WarningBranch is not the default.",
      "No production: FailedThe spec names production. Staging is the only environment.",
    ]);
  });

  it("says when nothing has run", () => {
    render(<ValidationChecklist checks={[]} />);

    expect(screen.getByText("No checks have run yet.")).toBeInTheDocument();
  });
});
