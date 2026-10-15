import { describe, expect, it } from "vitest";

import * as captured from "@/test/fixtures/queue";

import {
  formatEstimate,
  formatWait,
  jobTypeLabel,
  missingUpstreamNote,
  optimizerStatus,
  ranked,
} from "./queueModel";

const firstOf = (queue: typeof captured.group) => {
  const item = queue.items[0];
  if (!item) {
    throw new Error("the fixture has no items");
  }
  return item;
};

describe("the queue model", () => {
  it("names each Jenkins job class the plugin reports in words", () => {
    expect(jobTypeLabel("FreeStyleProject")).toBe("Freestyle");
    expect(jobTypeLabel("WorkflowJob")).toBe("Pipeline");
    expect(jobTypeLabel("MavenModuleSet")).toBe("Maven");
    expect(jobTypeLabel("unknown")).toBe("Unknown");
    // A class it has no word for is shown as the plugin sent it, never dropped.
    expect(jobTypeLabel("MatrixProject")).toBe("MatrixProject");
  });

  it("prints the plugin's estimates, and says when there is none", () => {
    expect(formatEstimate(null)).toBe("No history");
    // it-revision-upstream's build takes 0.226 s: not "0s".
    expect(formatEstimate(0.226)).toBe("Under 1s");
    expect(formatEstimate(3.535)).toBe("4s");
    expect(formatEstimate(33.306)).toBe("33s");
    expect(formatEstimate(80)).toBe("1m 20s");
  });

  it("prints a wait in seconds for the first minute, then in whole minutes", () => {
    expect(formatWait(6.642)).toBe("6s");
    expect(formatWait(59.9)).toBe("59s");
    // ranking-aged.json: five minutes, the first aging step.
    expect(formatWait(300.755)).toBe("5m");
    expect(formatWait(17 * 60 + 40)).toBe("17m");
    expect(formatWait(3_900)).toBe("1h 05m");
    expect(formatWait(-1)).toBe("0s");
  });

  it("names the upstream jobs a job depends on that Jenkins does not have", () => {
    const item = firstOf(captured.group);

    expect(missingUpstreamNote(item)).toBeNull();
    expect(missingUpstreamNote({ ...item, unresolved_dependencies: ["fs-gone-build"] })).toBe(
      "Upstream job not found: fs-gone-build",
    );
    expect(
      missingUpstreamNote({ ...item, unresolved_dependencies: ["fs-a-build", "fs-b-build"] }),
    ).toBe("Upstream jobs not found: fs-a-build, fs-b-build");
  });

  it("keeps the plugin's rank order, whatever order the items arrive in", () => {
    const shuffled = { ...captured.group, items: [...captured.group.items].reverse() };

    expect(ranked(shuffled).map(({ rank }) => rank)).toEqual([1, 2, 3, 4, 5]);
  });

  it("says whether the optimizer is ordering the queue", () => {
    expect(optimizerStatus(captured.threeWaiting)).toBe("Optimizer on");
    expect(optimizerStatus(captured.optimizerOff)).toBe("Optimizer off: Jenkins' own order");
    expect(optimizerStatus(captured.unavailable)).toBeNull();
  });
});
