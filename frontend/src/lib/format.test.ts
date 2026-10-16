import { describe, expect, it } from "vitest";

import {
  formatDuration,
  formatPercent,
  formatScore,
  formatTimeOfDay,
  formatWhen,
  ordinal,
  parseApiTime,
} from "./format";

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

  it("reads an API time without an offset as UTC, and one with an offset as it says", () => {
    // SQLite's form, as captured, and PostgreSQL's.
    expect(parseApiTime("2026-10-16T03:13:50.574908").toISOString()).toBe("2026-10-16T03:13:50.574Z");
    expect(parseApiTime("2026-10-16T03:13:51.047233Z").toISOString()).toBe("2026-10-16T03:13:51.047Z");
    expect(parseApiTime("2026-10-16T05:13:50+02:00").toISOString()).toBe("2026-10-16T03:13:50.000Z");
  });

  it("prints when something happened: the time today, the date before that", () => {
    const now = new Date(2026, 9, 16, 15, 0);

    expect(formatWhen(new Date(2026, 9, 16, 9, 5), now)).toBe("09:05");
    expect(formatWhen(new Date(2026, 9, 14, 23, 59), now)).toBe("14 Oct 23:59");
    expect(formatWhen(new Date(2025, 0, 2, 8, 0), now)).toBe("2 Jan 2025 08:00");
  });

  it("prints a ratio as a whole percentage", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(2 / 3)).toBe("67%");
    expect(formatPercent(1)).toBe("100%");
  });

  it("prints a time of day on the 24-hour clock, padded", () => {
    expect(formatTimeOfDay(new Date(2026, 9, 16, 9, 5, 7))).toBe("09:05:07");
    expect(formatTimeOfDay(new Date(2026, 9, 16, 23, 59, 59))).toBe("23:59:59");
  });
});
