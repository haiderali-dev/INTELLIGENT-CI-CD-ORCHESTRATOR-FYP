import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  apiHeaders,
  askAndApprove,
  finishBuilds,
  rankingWithHighAboveLow,
  reset,
  setRanking,
  signIn,
} from "./support";

/**
 * T6.9: every screen in light and dark at 1440 px and 390 px, into docs/screenshots/, from the
 * production build against the backend in fake mode. Run with `SCREENSHOTS=1 npx playwright test
 * --project=screenshots`. The data is made through the API first, the way the assistants make it:
 * a freestyle chain under way, a failed run with the real failing log, and a Pipeline waiting in
 * the plugin's ranking.
 */

const OUT = new URL("../../docs/screenshots/", import.meta.url);
const WIDTHS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;
const SCHEMES = ["light", "dark"] as const;

test.describe.configure({ mode: "serial" });

const made: { freestyleChat: string; pipelineChat: string; failedChain: string } = {
  freestyleChat: "",
  pipelineChat: "",
  failedChain: "",
};

/** Until the tracker has seen what the fake Jenkins did: it polls every 3 seconds. */
async function chainStatus(request: APIRequestContext, headers: Record<string, string>, chain: string, status: string) {
  await expect
    .poll(async () => ((await (await request.get(`/api/chains/${chain}`, { headers })).json()) as { status: string }).status, {
      timeout: 20_000,
    })
    .toBe(status);
}

test("makes the data the screens show", async ({ request }) => {
  await reset(request);
  const headers = await apiHeaders(request, "developer");

  // A failed run: auth-service's tests fail on the real failing log.
  const failed = await askAndApprove(request, headers, "freestyle", "Build, test and deploy the latest commit of auth-service to staging");
  await finishBuilds(request, "FAILURE");
  await chainStatus(request, headers, failed.chain, "FAILURE");
  made.failedChain = failed.chain;

  // A freestyle chain under way: its build passed, its tests have not started.
  const running = await askAndApprove(request, headers, "freestyle", "Build, test and deploy the latest commit of payment-service to staging");
  await finishBuilds(request, "SUCCESS");
  made.freestyleChat = running.chat;

  // A Pipeline waiting in the queue, first in the plugin's ranking.
  const waiting = await askAndApprove(request, headers, "pipeline", "Build, test and deploy the latest commit of auth-service to staging");
  made.pipelineChat = waiting.chat;
  const ranking = rankingWithHighAboveLow() as { items: { jobName: string }[]; queueLength: number };
  const card = (await (await request.get(`/api/chains/${waiting.chain}`, { headers })).json()) as { jobs: { name: string }[] };
  const first = ranking.items[0];
  if (first) {
    first.jobName = card.jobs[0]?.name ?? first.jobName;
  }
  // And a job held for its upstream, from the live recording of 2026-10-20 (ranking-held.json), so
  // the Queue page's Held back list is on the screenshots too (D-066).
  const held = JSON.parse(
    readFileSync(new URL("../../backend/tests/data/plugin/ranking-held.json", import.meta.url), "utf8"),
  ) as { heldItems: unknown[] };
  await setRanking(request, { ...ranking, heldItems: held.heldItems });
});

/** Each screen at both widths in both schemes, from one page load: the viewport and colour scheme
 * change in place, and the theme follows the scheme because it is set to System. */
async function capture(
  page: Page,
  name: string,
  ready: (page: Page) => Promise<void>,
  fullPage = true,
) {
  await page.evaluate(() => {
    localStorage.setItem("orchestrator.theme", "system");
  });
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await page.reload();
  for (const viewport of WIDTHS) {
    await page.setViewportSize(viewport);
    for (const scheme of SCHEMES) {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await ready(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
      await page.screenshot({
        path: fileURLToPath(new URL(`${name}-${String(viewport.width)}-${scheme}.png`, OUT)),
        fullPage,
        animations: "disabled",
      });
    }
  }
}

const quiet = async (page: Page) => {
  await expect(page.getByText(/^(Loading|Checking|Reading)/)).toHaveCount(0, { timeout: 15_000 });
};

test("the sign-in page", async ({ page }) => {
  await page.goto("/sign-in");
  await capture(page, "sign-in", async (p) => {
    await expect(p.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  });
});

test("every page a Developer uses", async ({ page }) => {
  await signIn(page, "developer");
  const screens: [string, string, (p: Page) => Promise<void>][] = [
    ["overview", "/", async (p) => {
      await expect(p.getByRole("list", { name: "Recent results" })).toBeVisible();
      await quiet(p);
    }],
    ["freestyle-assistant", `/assistants/freestyle/${made.freestyleChat}`, async (p) => {
      await expect(p.getByRole("list", { name: "Conversation with the Freestyle Assistant" })).toBeVisible();
      await quiet(p);
    }],
    ["pipeline-assistant", `/assistants/pipeline/${made.pipelineChat}`, async (p) => {
      await expect(p.getByRole("list", { name: "Conversation with the Pipeline Assistant" })).toBeVisible();
      await quiet(p);
    }],
    ["queue", "/queue", async (p) => {
      await expect(p.getByText("Ranked by score, highest first. Each bar shows what its score is made of.")).toBeVisible();
      await quiet(p);
    }],
    ["jobs-and-runs", `/runs?chain=${made.failedChain}`, async (p) => {
      await expect(p.getByText(/Finished: FAILURE/)).toBeVisible();
      await quiet(p);
    }],
    ["analytics", "/analytics", async (p) => {
      await expect(p.getByRole("list", { name: "Runs by result" })).toBeVisible();
      await quiet(p);
    }],
    ["service-catalog", "/catalog", async (p) => {
      await expect(p.getByText("Reachable").first()).toBeVisible();
      await quiet(p);
    }],
    ["admin-as-developer", "/admin", async (p) => {
      await expect(p.getByText("Only Admins can use this page.")).toBeVisible();
    }],
  ];
  for (const [name, path, ready] of screens) {
    await page.goto(path);
    // The assistants are app screens: the thread scrolls under a composer pinned to the bottom
    // of the screen, which a full-page capture would freeze mid-page. They are shown as seen.
    await capture(page, name, ready, !name.endsWith("-assistant"));
  }
});

test("the Admin page", async ({ page }) => {
  await signIn(page, "admin");
  await page.goto("/admin");
  await capture(page, "admin", async (p) => {
    await expect(p.getByText(/^Entries 1 to /)).toBeVisible();
    await quiet(p);
  });
});
