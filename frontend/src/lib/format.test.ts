import { describe, expect, it } from "vitest";

import { formatDuration, formatScore, ordinal } from "./format";

describe("format", () => {
  it("prints scores with three decimals, as Appendix C does", () => {
    expect(formatScore(0.633)).toBe("0.633");
    expect(formatScore(0.65)).toBe("0.650");
    expect(formatScore(1)).toBe("1.000");
  });

  it("names queue positions as ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "22nd",
      "23rd",
      "101st",
      "111th",
    ]);
  });

  it("prints durations so a column of them lines up", () => {
    expect(formatDuration(40_000)).toBe("40s");
    expect(formatDuration(80_000)).toBe("1m 20s");
    expect(formatDuration(120_000)).toBe("2m 00s");
    expect(formatDuration(3_900_000)).toBe("1h 05m");
    expect(formatDuration(-5)).toBe("0s");
  });
});
