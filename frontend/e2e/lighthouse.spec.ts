import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";
import lighthouse, { desktopConfig, type Flags, type Result } from "lighthouse";
import puppeteer, { type Page } from "puppeteer-core";

import { ACCOUNTS, apiHeaders, askAndApprove, finishBuilds, reset } from "./support";

/**
 * Phase 6's acceptance: a Lighthouse accessibility score of 95 or more on both assistant pages
 * (BUILD_PROMPT Part 7). Run with `LIGHTHOUSE=1 npx playwright test --project=lighthouse`, against
 * the production build and the backend in fake mode, as the flows are (D-062).
 *
 * The session lives in sessionStorage, which a Lighthouse run of its own starts without, so it would
 * audit the sign-in page. Here Puppeteer drives the installed Chrome, signs in through the form, and
 * Lighthouse audits that same tab with its storage reset off. Each assistant page is audited empty
 * and with a chat that has a plan and a run card, in light and dark, at Lighthouse's mobile and
 * desktop settings. The reports and a summary go to .tmp/lighthouse/.
 */

const OUT = new URL("../../.tmp/lighthouse/", import.meta.url);
const FLOOR = 0.95;
const THEMES = ["light", "dark"] as const;
const FORM_FACTORS = ["mobile", "desktop"] as const;
const ASSISTANTS = { freestyle: "Freestyle Assistant", pipeline: "Pipeline Assistant" } as const;

type Assistant = keyof typeof ASSISTANTS;

interface Audited {
  name: string;
  assistant: Assistant;
  path: string;
  theme: (typeof THEMES)[number];
  formFactor: (typeof FORM_FACTORS)[number];
  score: number | null;
  failing: string[];
  warnings: string[];
}

/** Signs in through the form, waiting out the sign-in limit as the flows do (support.ts). */
async function signInThroughTheForm(page: Page, base: string): Promise<void> {
  const { email, password } = ACCOUNTS.developer;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.goto(`${base}/sign-in`);
    await page.locator('input[type="email"]').fill(email);
    await page.locator('input[autocomplete="current-password"]').fill(password);
    const [answer] = await Promise.all([
      page.waitForResponse(
        (response) => response.url().endsWith("/api/auth/login") && response.request().method() === "POST",
      ),
      page.locator('::-p-aria([name="Sign in"][role="button"])').click(),
    ]);
    if (answer.status() !== 429) {
      expect(answer.ok(), `sign-in answered HTTP ${String(answer.status())}`).toBe(true);
      await page.waitForFunction(() => window.location.pathname !== "/sign-in");
      return;
    }
    const body = (await answer.json()) as { error?: { details?: { retry_after_seconds?: number } } };
    await new Promise((resolve) => setTimeout(resolve, ((body.error?.details?.retry_after_seconds ?? 12) + 1) * 1000));
  }
  throw new Error("the sign-in limit never let the audit through");
}

/** The category's weighted audits that did not pass, each with how many elements it named. */
function failingAudits(lhr: Result): string[] {
  const category = lhr.categories.accessibility;
  if (!category) {
    return ["no accessibility category in the report"];
  }
  return category.auditRefs.flatMap(({ id, weight }) => {
    const audit = lhr.audits[id];
    if (!audit || weight === 0 || audit.score === null || audit.score >= 1) {
      return [];
    }
    const details: unknown = audit.details;
    const items =
      typeof details === "object" && details !== null && "items" in details && Array.isArray(details.items)
        ? details.items.length
        : 0;
    return [`${id} (${String(items)} element${items === 1 ? "" : "s"}): ${audit.title}`];
  });
}

test("both assistant pages score 95 or more for accessibility", async ({ request, baseURL }) => {
  test.setTimeout(20 * 60_000);
  const base = baseURL ?? "";

  // The data a person would have: a freestyle chain under way and a Pipeline waiting to start.
  await reset(request);
  const headers = await apiHeaders(request, "developer");
  const freestyle = await askAndApprove(
    request,
    headers,
    "freestyle",
    "Build, test and deploy the latest commit of payment-service to staging",
  );
  await finishBuilds(request, "SUCCESS");
  const pipeline = await askAndApprove(
    request,
    headers,
    "pipeline",
    "Build, test and deploy the latest commit of auth-service to staging",
  );

  const pages: { name: string; assistant: Assistant; path: string }[] = [
    { name: "freestyle-new-chat", assistant: "freestyle", path: "/assistants/freestyle" },
    { name: "freestyle-chat", assistant: "freestyle", path: `/assistants/freestyle/${freestyle.chat}` },
    { name: "pipeline-new-chat", assistant: "pipeline", path: "/assistants/pipeline" },
    { name: "pipeline-chat", assistant: "pipeline", path: `/assistants/pipeline/${pipeline.chat}` },
  ];

  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ channel: "chrome", headless: true });
  const audited: Audited[] = [];
  let lighthouseVersion = "";
  try {
    const page = await browser.newPage();
    await signInThroughTheForm(page, base);

    for (const target of pages) {
      for (const theme of THEMES) {
        for (const formFactor of FORM_FACTORS) {
          // The stored choice is applied before the first paint (index.html), so Lighthouse loads
          // the page in this theme.
          await page.goto(`${base}${target.path}`);
          await page.evaluate((value) => {
            localStorage.setItem("orchestrator.theme", value);
          }, theme);

          const flags: Flags = {
            logLevel: "error",
            output: "html",
            onlyCategories: ["accessibility"],
            // Keeps the session, which is in this tab's storage.
            disableStorageReset: true,
          };
          const outcome = await lighthouse(
            `${base}${target.path}`,
            flags,
            formFactor === "desktop" ? desktopConfig : undefined,
            page,
          );
          if (!outcome) {
            throw new Error(`Lighthouse returned nothing for ${target.path}`);
          }
          const { lhr, report } = outcome;
          lighthouseVersion = lhr.lighthouseVersion;
          const name = `${target.name}-${formFactor}-${theme}`;
          writeFileSync(fileURLToPath(new URL(`${name}.html`, OUT)), Array.isArray(report) ? report.join("\n") : report);

          // The page audited must be the one asked for, signed in and in the theme asked for: a
          // lost session would have audited the sign-in page instead.
          expect(new URL(lhr.finalDisplayedUrl).pathname, name).toBe(target.path);
          const shown = await page.evaluate(() => ({
            path: window.location.pathname,
            heading: document.querySelector("h1")?.textContent ?? "",
            theme: document.documentElement.dataset.theme ?? "",
          }));
          expect(shown, name).toEqual({ path: target.path, heading: ASSISTANTS[target.assistant], theme });

          audited.push({
            name,
            assistant: target.assistant,
            path: target.path,
            theme,
            formFactor,
            score: lhr.categories.accessibility?.score ?? null,
            failing: failingAudits(lhr),
            warnings: lhr.runWarnings.map(String),
          });
        }
      }
    }
  } finally {
    await browser.close();
  }

  writeFileSync(
    fileURLToPath(new URL("summary.json", OUT)),
    `${JSON.stringify({ lighthouse: lighthouseVersion, floor: FLOOR, audited }, null, 2)}\n`,
  );
  for (const { name, score, failing } of audited) {
    console.log(`${name}: ${score === null ? "no score" : String(Math.round(score * 100))}${failing.length ? ` (${failing.join("; ")})` : ""}`);
  }
  const below = audited.filter(({ score }) => score === null || score < FLOOR);
  expect(below, "audits under the floor").toEqual([]);
});
