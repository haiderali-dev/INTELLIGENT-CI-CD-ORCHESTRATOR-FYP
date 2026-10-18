import { readFileSync } from "node:fs";

import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export type Role = "admin" | "developer";

function env(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set. Run the flows with "npx playwright test".`);
  }
  return value;
}

/** The two accounts the browser backend seeds, made up for this run (playwright.config.ts). */
export const ACCOUNTS: Readonly<Record<Role, { email: string; password: string }>> = {
  admin: { email: env("E2E_ADMIN_EMAIL"), password: env("E2E_ADMIN_PASSWORD") },
  developer: { email: env("E2E_DEVELOPER_EMAIL"), password: env("E2E_DEVELOPER_PASSWORD") },
};

/**
 * Signs in through the form, as a person does, and waits for the shell. Sign-in keeps its real
 * limits, five a minute per account and thirty per address, which every flow shares; when the
 * backend answers 429, this waits as long as it asks, then tries again.
 */
export async function signIn(page: Page, role: Role, next = "/"): Promise<void> {
  await page.goto(next === "/" ? "/sign-in" : `/sign-in?next=${encodeURIComponent(next)}`);
  await submitSignIn(page, role);
}

/** Fills and sends the sign-in form already on the page, waiting out the limit as `signIn` does. */
export async function submitSignIn(page: Page, role: Role): Promise<void> {
  await submitCredentials(page, ACCOUNTS[role].email, ACCOUNTS[role].password);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/**
 * Sends the sign-in form with these credentials until the backend answers with something other than
 * its rate limit: then the page shows that answer, for the flow to judge. A 429 is waited out for as
 * long as the backend asks (`retry_after_seconds`), so no flow ever loosens the limit.
 */
export async function submitCredentials(page: Page, email: string, password: string): Promise<void> {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    const [answer] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/auth/login") && response.request().method() === "POST",
      ),
      page.getByRole("button", { name: "Sign in" }).click(),
    ]);
    if (answer.status() !== 429) {
      return;
    }
    const body = (await answer.json()) as { error?: { details?: { retry_after_seconds?: number } } };
    const seconds = body.error?.details?.retry_after_seconds ?? 12;
    await page.waitForTimeout(Math.ceil(seconds) * 1000 + 500);
  }
  throw new Error(`the sign-in limit never let ${email} through`);
}

/** An assistant's conversation, and its newest message: the reply once it has come. */
export const thread = (page: Page, assistant: "Freestyle" | "Pipeline") =>
  page.getByRole("list", { name: `Conversation with the ${assistant} Assistant` });

export const newest = (page: Page, assistant: "Freestyle" | "Pipeline") =>
  thread(page, assistant).locator(":scope > li").last();

/** A toast, by its exact words: Radix also announces it in a live region of its own. */
export const toast = (page: Page, words: string) => page.getByText(words, { exact: true });

/**
 * Tab until `target` has focus, as someone using only the keyboard would. Looking at which element
 * has focus is not an action; every action in such a flow is a key press.
 */
export async function tabTo(page: Page, target: Locator, limit = 80): Promise<void> {
  for (let presses = 0; presses < limit; presses += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) {
      return;
    }
    await page.keyboard.press("Tab");
  }
  throw new Error(`Tab never reached the target in ${String(limit)} presses`);
}

/** The browser backend's own controls (backend/browser_backend.py), which the app never has. */
async function control(request: APIRequestContext, path: string, data: unknown): Promise<void> {
  const response = await request.post(`${env("E2E_BACKEND_URL")}/__e2e/${path}`, { data });
  expect(response.ok(), `${path}: HTTP ${String(response.status())}`).toBe(true);
}

/** Every running chain cancelled, the model answering and an empty ranking: a clean start. */
export const reset = (request: APIRequestContext) => control(request, "reset", {});

export const switchModel = (request: APIRequestContext, answering: boolean) =>
  control(request, "model", { answering });

export const setRanking = (request: APIRequestContext, ranking: unknown) =>
  control(request, "ranking", ranking);

/** Every queued build starts and ends with `result`; a FAILURE carries the real failing log. */
export const finishBuilds = (request: APIRequestContext, result: "SUCCESS" | "FAILURE") =>
  control(request, "builds", { result });

/**
 * Signs in through the API, for making data before a page is opened, and returns the header that
 * carries the token. A 429 is waited out as `submitCredentials` does.
 */
export async function apiHeaders(request: APIRequestContext, role: Role): Promise<Record<string, string>> {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const answer = await request.post("/api/auth/login", { data: ACCOUNTS[role] });
    if (answer.status() !== 429) {
      expect(answer.ok()).toBe(true);
      const { access_token: token } = (await answer.json()) as { access_token: string };
      return { Authorization: `Bearer ${token}` };
    }
    const body = (await answer.json()) as { error?: { details?: { retry_after_seconds?: number } } };
    await new Promise((resolve) => setTimeout(resolve, ((body.error?.details?.retry_after_seconds ?? 12) + 1) * 1000));
  }
  throw new Error("the sign-in limit never let the setup through");
}

/** Asks an assistant, generates the plan and approves it, as the pages do. Returns the chat and chain. */
export async function askAndApprove(
  request: APIRequestContext,
  headers: Record<string, string>,
  assistant: "freestyle" | "pipeline",
  text: string,
): Promise<{ chat: string; chain: string }> {
  const chat = (await (await request.post(`/api/assistants/${assistant}/conversations`, { headers })).json()) as { id: string };
  const sent = await request.post(`/api/conversations/${chat.id}/messages`, { headers, data: { text } });
  expect(sent.ok(), await sent.text()).toBe(true);
  const { command } = (await sent.json()) as { command: { id: string } | null };
  expect(command, `no command for "${text}"`).not.toBeNull();
  const plan = await request.post(`/api/commands/${command?.id ?? ""}/generate`, { headers });
  expect(plan.ok(), await plan.text()).toBe(true);
  const { id } = (await plan.json()) as { id: string };
  const approved = await request.post(`/api/pipelines/${id}/approve`, {
    headers: { ...headers, "Idempotency-Key": `e2e-${id}` },
  });
  expect(approved.ok(), await approved.text()).toBe(true);
  const { result } = (await approved.json()) as { result: { chain_id: string } };
  return { chat: chat.id, chain: result.chain_id };
}

interface RecordedItem {
  rank: number;
  jobName: string;
  level: string;
  score: number;
  ownScore: number;
  baseScore: number;
  components: { urgency: number; dependency: number; executionTime: number; aging: number };
}

/**
 * The plugin's ranking with a HIGH job above a LOW one: the recording of three waiting jobs from the
 * live plugin (backend/tests/data/plugin), with its MEDIUM job made LOW. That job's urgency factor
 * becomes LOW's 0.3, and its scores are worked out again by the report's formula, 0.5U + 0.3D +
 * 0.2T plus aging: 0.5 x 0.3 = 0.150. Everything else is as recorded.
 */
export function rankingWithHighAboveLow(): unknown {
  const recorded = JSON.parse(
    readFileSync(new URL("../../backend/tests/data/plugin/ranking-three-waiting.json", import.meta.url), "utf8"),
  ) as { items: RecordedItem[] };
  const low = recorded.items[2];
  if (!low) {
    throw new Error("the recording has no third item");
  }
  const { dependency, executionTime, aging } = low.components;
  const base = 0.5 * 0.3 + 0.3 * dependency + 0.2 * executionTime;
  Object.assign(low, {
    level: "LOW",
    components: { ...low.components, urgency: 0.3 },
    baseScore: base,
    ownScore: base + aging,
    score: base + aging,
  });
  return recorded;
}
