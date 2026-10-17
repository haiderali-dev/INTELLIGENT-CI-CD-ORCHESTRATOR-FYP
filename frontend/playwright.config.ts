import { randomBytes } from "node:crypto";

import { defineConfig } from "@playwright/test";

/**
 * The browser flows of 4.7.6 (T6.8), run against the backend in fake mode: `backend/browser_backend.py`
 * starts the real app with LLM_MODE=fake and in-memory stand-ins for Jenkins, its plugin and Git, and
 * `vite preview` serves the built app and proxies /api and /ws to it.
 *
 * The two accounts are made up for each run and handed to both through the environment: nothing
 * here is a real credential. Set in the runner's own process, so the workers it starts inherit the
 * same ones instead of making new ones.
 */
const madeUp = () => randomBytes(18).toString("base64url");
process.env.E2E_ADMIN_EMAIL ??= "e2e-admin@example.com";
process.env.E2E_ADMIN_PASSWORD ??= `admin-${madeUp()}`;
process.env.E2E_DEVELOPER_EMAIL ??= "e2e-developer@example.com";
process.env.E2E_DEVELOPER_PASSWORD ??= `developer-${madeUp()}`;

/** Away from the usual 8000 and 5173, so a developer's own stack and dev server can keep running. */
export const BACKEND_PORT = 8799;
/** The uv to start the backend with: `verify.py` passes its own (D-010), anything else finds one. */
const UV = process.env.E2E_UV ?? "uv";
const FRONTEND_PORT = 5174;
process.env.E2E_BACKEND_URL ??= `http://127.0.0.1:${String(BACKEND_PORT)}`;

export default defineConfig({
  testDir: "./e2e",
  // One backend serves every flow, with its per-service chain locks and its sign-in limit, so the
  // flows take turns.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: `http://localhost:${String(FRONTEND_PORT)}`,
    // The installed Google Chrome, here and on GitHub's runners, so no browser is downloaded.
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // The flows always; T6.9's screenshots (docs/screenshots/) only when asked for with SCREENSHOTS=1,
  // since they rewrite committed files; the Lighthouse audits only with LIGHTHOUSE=1, since they
  // take minutes.
  projects: [
    { name: "flows", testIgnore: /(screenshots|lighthouse)\.spec\.ts/ },
    ...(process.env.SCREENSHOTS ? [{ name: "screenshots", testMatch: /screenshots\.spec\.ts/ }] : []),
    ...(process.env.LIGHTHOUSE ? [{ name: "lighthouse", testMatch: /lighthouse\.spec\.ts/ }] : []),
  ],
  webServer: [
    {
      // --no-sync: the backend is installed already, and a sync here would try to rebuild it (CLAUDE.md).
      command: `"${UV}" run --no-sync python browser_backend.py`,
      cwd: "../backend",
      url: `http://127.0.0.1:${String(BACKEND_PORT)}/api/health/live`,
      env: {
        E2E_BACKEND_PORT: String(BACKEND_PORT),
        E2E_FRONTEND_ORIGIN: `http://localhost:${String(FRONTEND_PORT)}`,
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // The production build, served by `vite preview` with the same /api and /ws proxy as the dev
      // server: what users get, and no dependency optimizer reloading the page mid-flow.
      command: `npx vite build && npx vite preview --port ${String(FRONTEND_PORT)} --strictPort`,
      url: `http://localhost:${String(FRONTEND_PORT)}`,
      env: { BACKEND_URL: `http://127.0.0.1:${String(BACKEND_PORT)}` },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
