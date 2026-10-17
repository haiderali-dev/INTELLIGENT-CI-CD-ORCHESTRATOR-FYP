import { afterEach, describe, expect, it, vi } from "vitest";

import { readPreference, resolveTheme, storePreference, THEME_STORAGE_KEY } from "./theme";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("theme preference", () => {
  it("is light until the viewer chooses, because projectors wash dark themes out", () => {
    expect(readPreference()).toBe("light");
  });

  it("remembers a choice, and ignores anything it did not write", () => {
    storePreference("system");
    expect(readPreference()).toBe("system");

    window.localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readPreference()).toBe("light");
  });

  it("falls back to light when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => {
      storePreference("dark");
    }).not.toThrow();
    expect(readPreference()).toBe("light");
  });

  it.each([
    ["light", false, "light"],
    ["light", true, "light"],
    ["dark", false, "dark"],
    ["system", false, "light"],
    ["system", true, "dark"],
  ] as const)("%s with a dark system (%s) is %s", (preference, prefersDark, expected) => {
    expect(resolveTheme(preference, prefersDark)).toBe(expected);
  });
});
