import { describe, expect, it } from "vitest";

import {
  contributions,
  describeScore,
  endPercent,
  isInherited,
  ownScore,
  percentOfScale,
  segments,
  type ScoreComponents,
} from "./scoreBarModel";

const WEIGHTS = { urgency: 0.5, dependency: 0.3, executionTime: 0.2 };

/** DESIGN.md section 6's test job: urgency 0.500, dependency 0.100, execution time 0.100 and aging
 * 0.050, own score 0.750, inheriting its group's 0.820. */
const TEST_JOB: ScoreComponents = {
  urgency: 1.0,
  dependency: 1 / 3,
  execution_time: 0.5,
  aging_bonus: 0.05,
  base_score: 0.7,
  own_score: 0.75,
};

/** it-revision-upstream as the live plugin ranked it on 2026-10-15
 * (backend/tests/data/plugin/ranking-group.json): MEDIUM, in a group of two, inheriting its HIGH
 * downstream's score. */
const RECORDED_UPSTREAM: ScoreComponents = {
  urgency: 0.6,
  dependency: 1.0,
  execution_time: 1.0,
  aging_bonus: 0.0,
  base_score: 0.8,
  own_score: 0.8,
};

const close = (values: number[]) => values.map((value) => Number(value.toFixed(3)));

describe("score bar arithmetic", () => {
  it("makes each segment weight times factor, with aging as a bonus", () => {
    const shares = contributions(TEST_JOB, WEIGHTS);

    expect(shares && close(Object.values(shares))).toEqual([0.5, 0.1, 0.1, 0.05]);
  });

  it("takes the weights from the API, never from the UI", () => {
    const shares = contributions(TEST_JOB, { urgency: 0.6, dependency: 0.2, executionTime: 0.2 });

    expect(shares && close(Object.values(shares))).toEqual([0.6, 0.067, 0.1, 0.05]);
    expect(contributions(TEST_JOB, { urgency: 0.5, dependency: 0.3 })).toBeNull();
  });

  it("knows an inherited score from its own, as the plugin defines them", () => {
    expect(ownScore(TEST_JOB)).toBeCloseTo(0.75);
    expect(isInherited(0.82, TEST_JOB)).toBe(true);
    expect(isInherited(0.75, TEST_JOB)).toBe(false);
    // Appendix C: own 0.633, effective 0.650.
    const appendixC = {
      urgency: 0.6,
      dependency: 1,
      execution_time: 0.165,
      aging_bonus: 0,
      base_score: 0.633,
      own_score: 0.633,
    };
    expect(isInherited(0.65, appendixC)).toBe(true);
    expect(isInherited(0.6334, appendixC)).toBe(false);
  });

  it("reads a live inherited score the way the plugin reported it", () => {
    const shares = contributions(RECORDED_UPSTREAM, WEIGHTS);
    if (!shares) {
      throw new Error("weights were complete");
    }

    expect(isInherited(0.979994, RECORDED_UPSTREAM)).toBe(true);
    expect(describeScore(0.979994, RECORDED_UPSTREAM, shares)).toBe(
      "Score 0.980, inherited from its group. Own score 0.800: urgency 0.300, dependency 0.300, execution time 0.200, aging 0.000.",
    );
  });

  it("names the score in DESIGN.md's words", () => {
    const shares = contributions(TEST_JOB, WEIGHTS);
    if (!shares) {
      throw new Error("weights were complete");
    }

    expect(describeScore(0.82, TEST_JOB, shares)).toBe(
      "Score 0.820, inherited from its group. Own score 0.750: urgency 0.500, dependency 0.100, execution time 0.100, aging 0.050.",
    );
    expect(describeScore(0.75, TEST_JOB, shares)).toBe(
      "Score 0.750: urgency 0.500, dependency 0.100, execution time 0.100, aging 0.050.",
    );
  });

  it("draws on one fixed scale from 0 to 1.15, segments side by side", () => {
    const shares = contributions(TEST_JOB, WEIGHTS);
    if (!shares) {
      throw new Error("weights were complete");
    }
    const drawn = segments(shares);

    expect(drawn.map(({ key }) => key)).toEqual(["urgency", "dependency", "executionTime", "aging"]);
    expect(close(drawn.map(({ startPercent }) => startPercent))).toEqual([0, 43.478, 52.174, 60.87]);
    expect(close(drawn.map(({ widthPercent }) => widthPercent))).toEqual([43.478, 8.696, 8.696, 4.348]);
    expect(drawn.map(({ last }) => last)).toEqual([false, false, false, true]);
    expect(close([endPercent(shares), percentOfScale(1), percentOfScale(1.15)])).toEqual([
      65.217, 86.957, 100,
    ]);
  });

  it("draws nothing for a factor of zero, and leaves no gap for it", () => {
    const drawn = segments({ urgency: 0.3, dependency: 0, executionTime: 0.1, aging: 0 });

    expect(drawn.map(({ key }) => key)).toEqual(["urgency", "executionTime"]);
    expect(drawn[1]?.startPercent).toBeCloseTo(percentOfScale(0.3));
    expect(drawn.map(({ last }) => last)).toEqual([false, true]);
  });
});
