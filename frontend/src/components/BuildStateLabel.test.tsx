import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BUILD_STATES, stateFromResult, type BuildState } from "./buildState";
import { BuildStateLabel } from "./BuildStateLabel";

const STATES = Object.keys(BUILD_STATES) as BuildState[];

describe("build states", () => {
  it("are an icon and a word, every one of them", () => {
    render(
      <ul>
        {STATES.map((state) => (
          <li key={state}>
            <BuildStateLabel state={state} />
          </li>
        ))}
      </ul>,
    );

    for (const word of ["Succeeded", "Failed", "Unstable", "Running", "Queued", "Aborted", "Not built"]) {
      const label = screen.getByText(word);
      expect(label.previousElementSibling?.tagName.toLowerCase()).toBe("svg");
    }
  });

  it("keep colour for succeeded, failed and unstable; the rest are Graphite", () => {
    const tones = Object.fromEntries(STATES.map((state) => [state, BUILD_STATES[state].tone]));

    expect(tones).toEqual({
      succeeded: "text-state-succeeded",
      failed: "text-state-failed",
      unstable: "text-state-unstable",
      running: "text-graphite",
      queued: "text-graphite",
      aborted: "text-graphite",
      "not-built": "text-graphite",
    });
  });

  it("turn only the running ring, and stop it under reduced motion", () => {
    const { container } = render(
      <>
        <BuildStateLabel state="running" />
        <BuildStateLabel state="queued" />
      </>,
    );
    const [running, queued] = [...container.querySelectorAll("svg")];

    expect(running).toHaveClass("animate-spin", "motion-reduce:animate-none");
    expect(queued).not.toHaveClass("animate-spin");
  });

  it("take a name for what they belong to", () => {
    render(<BuildStateLabel state="succeeded" label="Build succeeded" />);

    expect(screen.getByText("Build succeeded")).toBeInTheDocument();
  });

  it("are read from Jenkins' result words", () => {
    expect(
      ["SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT", "success", null, "SOMETHING"].map(
        stateFromResult,
      ),
    ).toEqual(["succeeded", "failed", "unstable", "aborted", "not-built", "succeeded", "running", "not-built"]);
  });
});
