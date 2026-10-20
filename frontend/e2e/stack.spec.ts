import { expect, test, type Page } from "@playwright/test";

/**
 * System tests of the running Compose stack, through its own frontend container: nginx serving the
 * build and proxying /api and /ws to the backend, the backend on PostgreSQL, the real jenkins-dev
 * and its two agents, and the plugin's live events coming back to the page. Nothing here is a
 * stand-in, unlike the flows (D-062), which run the backend in fake mode.
 *
 * Run with `python scripts/stack_system_test.py`, which creates a throwaway Developer account,
 * hands it to this file through STACK_EMAIL and STACK_PASSWORD, and deactivates it afterwards.
 * The stack's own Admin, whose password is in .env, is never used.
 */

const EMAIL = process.env.STACK_EMAIL ?? "";
const PASSWORD = process.env.STACK_PASSWORD ?? "";

test.describe.configure({ mode: "serial" });

test.beforeAll(() => {
  if (!EMAIL || !PASSWORD) {
    throw new Error("STACK_EMAIL and STACK_PASSWORD are not set. Run scripts/stack_system_test.py.");
  }
});

async function signInToStack(page: Page): Promise<void> {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/** Anything a page should never do: break its policy, throw, or get a server error back. */
function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) {
      problems.push(`CSP: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    problems.push(`page error: ${error.message}`);
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 500) {
      problems.push(`${String(response.status())} from ${response.url()}`);
    }
  });
  return problems;
}

test("every page loads through the stack's frontend, under its policy, with no server error", async ({ page }) => {
  const problems = watch(page);
  await signInToStack(page);

  const pages: [string, string][] = [
    ["/", "Overview"],
    ["/assistants/freestyle", "Freestyle Assistant"],
    ["/assistants/pipeline", "Pipeline Assistant"],
    ["/queue", "Queue"],
    ["/runs", "Jobs and runs"],
    ["/analytics", "Analytics"],
    ["/catalog", "Service catalog"],
  ];
  for (const [path, heading] of pages) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
  // The live events reached the page through nginx's /ws proxy.
  await page.goto("/queue");
  await expect(page.getByRole("list", { name: "Queue status" })).toContainText("Live");
  // The catalog's services were read from the stack's own catalog and their repositories reached.
  await page.goto("/catalog");
  await expect(page.getByText("payment-service").first()).toBeVisible();

  expect(problems).toEqual([]);
});

test("a freestyle build runs on the real Jenkins, and its run card follows it live", async ({ page }) => {
  test.setTimeout(6 * 60_000);
  const problems = watch(page);
  await signInToStack(page);
  await page.goto("/assistants/freestyle");

  const composer = page.getByRole("textbox", { name: "Message the Freestyle Assistant" });
  await composer.fill("Build payment-service from main");
  await composer.press("Enter");

  const thread = page.getByRole("list", { name: "Conversation with the Freestyle Assistant" });
  const card = thread.locator(":scope > li").last();
  await expect(card.getByRole("region", { name: "Intent" })).toContainText("payment-service", {
    timeout: 60_000,
  });
  await card.getByRole("button", { name: "Generate" }).click();

  const preview = page.getByRole("complementary", { name: "Preview" });
  await preview.getByRole("tab", { name: "Checks" }).click();
  // Validation includes the real controller: the job names are checked against jenkins-dev.
  await expect(preview.getByRole("list", { name: "Progress" })).toContainText("Validated", {
    timeout: 60_000,
  });
  await preview.getByRole("button", { name: "Approve and run" }).click();

  const dialog = page.getByRole("alertdialog", { name: "Approve and run" });
  await expect(dialog).toContainText(/(Creates|Updates) 1 job and starts fs-payment-service-build on main/);
  await dialog.getByRole("button", { name: "Approve and run" }).click();

  const run = page.getByRole("region", { name: "Run of fs-payment-service-build" });
  await expect(run).toBeVisible({ timeout: 30_000 });
  // Built on an agent by the real Jenkins; the card learns of it from the plugin's events and the
  // backend's tracker, over the WebSocket, without a reload.
  await expect(run).toContainText("fs-payment-service-build succeeded", { timeout: 5 * 60_000 });

  expect(problems).toEqual([]);
});

test("a Pipeline build is linted and run by the real Jenkins, its stages followed live", async ({ page }) => {
  test.setTimeout(8 * 60_000);
  const problems = watch(page);
  await signInToStack(page);
  await page.goto("/assistants/pipeline");

  const composer = page.getByRole("textbox", { name: "Message the Pipeline Assistant" });
  await composer.fill("Build auth-service from main");
  await composer.press("Enter");

  const thread = page.getByRole("list", { name: "Conversation with the Pipeline Assistant" });
  const card = thread.locator(":scope > li").last();
  await expect(card.getByRole("region", { name: "Intent" })).toContainText("auth-service", {
    timeout: 60_000,
  });
  await card.getByRole("button", { name: "Generate" }).click();

  const preview = page.getByRole("complementary", { name: "Preview" });
  await preview.getByRole("tab", { name: "Jenkinsfile" }).click();
  await expect(preview.getByText("pipeline {")).toBeVisible({ timeout: 60_000 });
  await preview.getByRole("tab", { name: "Checks" }).click();
  // The Jenkinsfile was linted by jenkins-dev's own declarative linter on the way to Validated.
  await expect(preview.getByRole("list", { name: "Progress" })).toContainText("Validated", {
    timeout: 60_000,
  });
  await preview.getByRole("button", { name: "Approve and run" }).click();
  await page
    .getByRole("alertdialog", { name: "Approve and run" })
    .getByRole("button", { name: "Approve and run" })
    .click();

  const run = page.getByRole("region", { name: /^Run of pl-auth-service/ });
  await expect(run).toBeVisible({ timeout: 30_000 });
  // The stages come from Jenkins' own stage view, tracked by the backend and pushed over /ws.
  await expect(run.getByRole("list", { name: "Stages" })).toContainText("Build succeeded", {
    timeout: 6 * 60_000,
  });

  expect(problems).toEqual([]);
});
