import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ScoreBar } from "./ScoreBar";
import type { ScoreComponents } from "./scoreBarModel";

const WEIGHTS = { urgency: 0.5, dependency: 0.3, executionTime: 0.2 };
const TEST_JOB: ScoreComponents = {
  urgency: 1.0,
  dependency: 1 / 3,
  execution_time: 0.5,
  aging_bonus: 0.05,
  base_score: 0.7,
};
const INHERITED_NAME =
  "Score 0.820, inherited from its group. Own score 0.750: urgency 0.500, dependency 0.100, execution time 0.100, aging 0.050.";

const segment = (container: HTMLElement, factor: string) =>
  container.querySelector<HTMLElement>(`[data-factor="${factor}"]`);

describe("ScoreBar", () => {
  it("reads without colour: one image named with the score and every part", () => {
    render(<ScoreBar score={0.82} parts={TEST_JOB} weights={WEIGHTS} />);

    expect(screen.getByRole("img", { name: INHERITED_NAME })).toBeInTheDocument();
    expect(screen.getByText("0.820")).toBeInTheDocument();
    expect(screen.getByText("inherited")).toBeInTheDocument();
  });

  it("marks the ceiling at 1.0, and an inherited score with an Ink tick", () => {
    const { container, rerender } = render(
      <ScoreBar score={0.82} parts={TEST_JOB} weights={WEIGHTS} />,
    );

    expect(container.querySelector('[data-mark="ceiling"]')).toHaveClass("bg-graphite");
    expect(container.querySelector('[data-mark="inherited"]')).toHaveClass("bg-ink");

    rerender(<ScoreBar score={0.75} parts={TEST_JOB} weights={WEIGHTS} />);

    expect(container.querySelector('[data-mark="inherited"]')).toBeNull();
    expect(screen.queryByText("inherited")).toBeNull();
    expect(
      screen.getByRole("img", {
        name: "Score 0.750: urgency 0.500, dependency 0.100, execution time 0.100, aging 0.050.",
      }),
    ).toBeInTheDocument();
  });

  it("draws the four segments in the formula's order and hues, rounding only the data end", () => {
    const { container } = render(<ScoreBar score={0.82} parts={TEST_JOB} weights={WEIGHTS} />);

    const drawn = [...container.querySelectorAll<HTMLElement>("[data-factor]")];
    expect(drawn.map((element) => element.dataset.factor)).toEqual([
      "urgency",
      "dependency",
      "executionTime",
      "aging",
    ]);
    expect(segment(container, "urgency")).toHaveClass("bg-factor-urgency");
    expect(segment(container, "aging")).toHaveClass("bg-factor-aging", "rounded-r-data");
    expect(segment(container, "urgency")).not.toHaveClass("rounded-r-data");
  });

  it("follows the weights the API reports", () => {
    // jsdom drops the widths, whose max() it cannot parse, so the segments' starts are compared.
    const { container, rerender } = render(
      <ScoreBar score={0.75} parts={TEST_JOB} weights={WEIGHTS} />,
    );
    const before = segment(container, "dependency")?.style.left;

    rerender(
      <ScoreBar
        score={0.75}
        parts={TEST_JOB}
        weights={{ urgency: 0.3, dependency: 0.5, executionTime: 0.2 }}
      />,
    );

    expect(before).toMatch(/^43\.47\d*%$/);
    expect(segment(container, "dependency")?.style.left).toMatch(/^26\.08\d*%$/);
  });

  it("draws nothing for a factor of zero", () => {
    const { container } = render(
      <ScoreBar
        score={0.35}
        parts={{ ...TEST_JOB, dependency: 0, aging_bonus: 0, base_score: 0.35, urgency: 0.3 }}
        weights={WEIGHTS}
      />,
    );

    expect(segment(container, "dependency")).toBeNull();
    expect(segment(container, "aging")).toBeNull();
    expect(segment(container, "executionTime")).toHaveClass("rounded-r-data");
  });

  it("says so instead of guessing when the weights are missing", () => {
    render(<ScoreBar score={0.82} parts={TEST_JOB} weights={{}} />);

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText(/Its parts cannot be shown/)).toBeInTheDocument();
  });

  it("gives the run card a legend with each contribution", () => {
    render(<ScoreBar size="card" score={0.82} parts={TEST_JOB} weights={WEIGHTS} />);

    for (const [label, value] of [
      ["Urgency", "0.500"],
      ["Dependency", "0.100"],
      ["Execution time", "0.100"],
      ["Aging", "0.050"],
    ] as const) {
      expect(screen.getByText(label).nextElementSibling).toHaveTextContent(value);
    }
  });

  it("shows the same words as a tooltip on keyboard focus", async () => {
    const user = userEvent.setup();
    render(<ScoreBar score={0.82} parts={TEST_JOB} weights={WEIGHTS} />);

    await user.tab();

    expect(screen.getByRole("img")).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(INHERITED_NAME);
  });
});
