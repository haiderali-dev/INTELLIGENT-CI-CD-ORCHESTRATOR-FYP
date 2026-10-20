import { describe, expect, it } from "vitest";

import { safeNext, signInPath } from "./next";

describe("where to go after signing in", () => {
  it("follows a path on this site, keeping its query and fragment", () => {
    expect(safeNext("/queue")).toBe("/queue");
    expect(safeNext("/runs?service=payment-service#latest")).toBe(
      "/runs?service=payment-service#latest",
    );
  });

  it("goes to the overview for anything that is not a path on this site", () => {
    for (const raw of [
      null,
      "",
      "queue",
      "https://elsewhere.example/",
      "//elsewhere.example/queue",
      "/\\elsewhere.example",
      "/\t/elsewhere.example",
      "javascript:alert(1)",
      // Another site's page, once the tab is stripped: the overview, not this site's /queue.
      "/\t/elsewhere.example/queue",
      // Paths that only become protocol-relative once resolved (security review, finding 8).
      "/.//evil.example",
      "/..//evil.example",
      "/a/..//evil.example",
      "/./\\evil.example",
      "/sign-in",
    ]) {
      expect(safeNext(raw), String(raw)).toBe("/");
    }
  });

  it("carries the page to return to, but not the overview", () => {
    expect(signInPath("/queue?view=all")).toBe("/sign-in?next=%2Fqueue%3Fview%3Dall");
    expect(signInPath("/")).toBe("/sign-in");
    expect(signInPath(null)).toBe("/sign-in");
    expect(signInPath("//elsewhere.example")).toBe("/sign-in");
  });
});
