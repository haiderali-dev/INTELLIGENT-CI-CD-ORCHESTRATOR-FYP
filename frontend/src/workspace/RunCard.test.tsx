import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunCard, type RunQueue } from "./RunCard";

const QUEUE: RunQueue = {
  rank: 1,
  score: 0.82,
  parts: { urgency: 1, dependency: 1 / 3, execution_time: 0.5, aging_bonus: 0.05, base_score: 0.7 },
  weights: { urgency: 0.5, dependency: 0.3, executionTime: 0.2 },
  waitingReason: null,
};

describe("RunCard", () => {
  it("says where the run waits, why, and what its score is made of", () => {
    render(<RunCard jobName="fs-payment-service-build" queue={QUEUE} />);

    const card = screen.getByRole("region", { name: "Run of fs-payment-service-build" });
    expect(within(card).getByText("1st in queue")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /^Score 0\.820, inherited/ })).toBeInTheDocument();
    expect(within(card).getByText("Waiting for a free executor")).toBeInTheDocument();
  });

  it("gives the plugin's reason when the run is blocked", () => {
    render(
      <RunCard
        jobName="fs-payment-service-test"
        queue={{ ...QUEUE, rank: 2, waitingReason: "Waits for fs-payment-service-build" }}
      />,
    );

    expect(screen.getByText("2nd in queue")).toBeInTheDocument();
    expect(screen.getByText("Waits for fs-payment-service-build")).toBeInTheDocument();
  });

  it("says the ranking is unavailable rather than drawing an empty bar", () => {
    render(
      <RunCard
        jobName="fs-payment-service-build"
        rankingUnavailable="The plugin did not answer on jenkins-baseline."
      />,
    );

    expect(screen.getByText("Ranking unavailable.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("names each stage with its state, then the result and how long it took", () => {
    render(
      <RunCard
        jobName="pl-payment-service"
        stages={[
          { name: "Build", state: "succeeded" },
          { name: "Test", state: "failed" },
          { name: "Deploy", state: "not-built" },
        ]}
        result={{ state: "failed", durationMs: 65_000 }}
      />,
    );

    const stages = within(screen.getByRole("list", { name: "Stages" })).getAllByRole("listitem");
    expect(stages.map((stage) => stage.textContent)).toEqual([
      "Build succeeded",
      "Test failed",
      "Deploy not started",
    ]);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("in 1m 05s")).toBeInTheDocument();
  });

  it("links to Jenkins in a new tab, and says so", () => {
    render(
      <RunCard jobName="fs-payment-service-build" jenkinsUrl="http://localhost:8080/job/x/12/" />,
    );

    const link = screen.getByRole("link", { name: "Open in Jenkins, opens in a new tab" });
    expect(link).toHaveAttribute("href", "http://localhost:8080/job/x/12/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("never links to anything but a web address", () => {
    render(<RunCard jobName="fs-payment-service-build" jenkinsUrl="javascript:alert(1)" />);

    expect(screen.queryByRole("link")).toBeNull();
  });
});
