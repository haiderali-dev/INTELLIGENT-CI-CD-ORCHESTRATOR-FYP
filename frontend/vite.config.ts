import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The backend for the dev server's proxy, so the app can call /api and /ws on its own origin.
// The Compose stack publishes the backend on 8000. VITE_API_BASE_URL, when set, makes the app call
// the backend directly instead (src/api/client.ts), and the proxy goes unused.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
  },
});
