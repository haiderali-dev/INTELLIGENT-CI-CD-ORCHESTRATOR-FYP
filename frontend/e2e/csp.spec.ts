import { expect, test } from "@playwright/test";

import { signIn } from "./support";

/**
 * The built app carries a Content-Security-Policy (vite.config.ts, security review finding 12),
 * and nothing it does breaks it: the theme script runs by its hash, the live-events socket and the
 * API connect, and code views load their styles. A violation is reported to the console, so any
 * one of them fails this flow.
 */
test("the app runs under its Content-Security-Policy without a single violation", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) {
      violations.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    violations.push(error.message);
  });

  await page.goto("/sign-in");
  const policy = await page
    .locator('meta[http-equiv="Content-Security-Policy"]')
    .getAttribute("content");
  expect(policy).toContain("script-src 'self' 'sha256-");
  expect(policy).not.toContain("script-src 'self' 'unsafe-inline'");

  await signIn(page, "developer");
  for (const path of ["/assistants/freestyle", "/assistants/pipeline", "/queue", "/runs", "/analytics", "/catalog"]) {
    await page.goto(path);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  }
  // The theme script ran: the page has its theme before React mounted.
  await expect(page.locator("html")).toHaveAttribute("data-theme", /^(light|dark)$/);

  expect(violations).toEqual([]);
});
