import { createHash } from "node:crypto";
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

/**
 * A Content-Security-Policy for the built app (independent security review, finding 12). The
 * refresh token lives in sessionStorage (D-054), so its safety rests on there being no XSS, and a
 * policy is the second line behind React's escaping.
 * - Scripts: this origin, plus the one inline script (the theme, set before first paint) by hash,
 *   so no other inline script can run.
 * - Styles allow 'unsafe-inline': CodeMirror and Radix set styles at run time.
 * - Connections: this origin (the /api and /ws proxy), plus VITE_API_BASE_URL's when set.
 * Build only: the dev server injects inline scripts of its own for hot reload.
 */
function contentSecurityPolicy(): Plugin {
  return {
    name: "content-security-policy",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(
          ([, body]) => `'sha256-${createHash("sha256").update(body).digest("base64")}'`,
        );
        const connect = ["'self'"];
        const api = process.env.VITE_API_BASE_URL;
        if (api) {
          const origin = new URL(api).origin;
          connect.push(origin, origin.replace(/^http/, "ws"));
        }
        const policy = [
          "default-src 'self'",
          ["script-src 'self'", ...inline].join(" "),
          "style-src 'self' 'unsafe-inline'",
          "img-src 'self' data:",
          "font-src 'self'",
          `connect-src ${connect.join(" ")}`,
          "object-src 'none'",
          "base-uri 'self'",
          "form-action 'self'",
        ].join("; ");
        return html.replace(
          "<head>",
          `<head>\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`,
        );
      },
    },
  };
}

// The backend for the dev server's proxy, so the app can call /api and /ws on its own origin.
// The Compose stack publishes the backend on 8000. VITE_API_BASE_URL, when set, makes the app call
// the backend directly instead (src/api/client.ts), and the proxy goes unused.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss(), contentSecurityPolicy()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Vitest empties every CSS import unless told otherwise, ?raw included. The token test reads
    // tokens.css as text to compare it with DESIGN.md.
    css: { include: [/tokens\.css/] },
    // `npm run coverage`: statement and branch coverage of the app's own code, for the testing
    // chapter's white-box measurements. The tests, their fixtures and the generated API types are
    // not the app.
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/api/schema.d.ts", "src/vite-env.d.ts"],
      reporter: ["text-summary", "json-summary", "json"],
      reportsDirectory: "coverage",
    },
  },
});
