/// <reference types="vitest" />
import fs from "node:fs";
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const PORT_HINT_FILE = path.resolve(process.cwd(), "data", ".server-port");
const DEFAULT_API_TARGET = "http://127.0.0.1:8001";

/**
 * The backend auto-increments from 8001 when the port is taken and publishes the real port in
 * data/.server-port. Reading it here keeps `pnpm dev` working instead of hard-coding 8001.
 */
function apiTarget() {
  const override = process.env.BILIBILI_API_TARGET;
  if (override) return override;
  try {
    const hint = JSON.parse(fs.readFileSync(PORT_HINT_FILE, "utf8")) as { host?: string; port?: number };
    if (hint?.port) return `http://${hint.host || "127.0.0.1"}:${hint.port}`;
  } catch {
    // No running backend or unreadable hint: fall back to the documented default port.
  }
  return DEFAULT_API_TARGET;
}

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": apiTarget(),
    },
  },
  test: {
    include: ["../tests/frontend/**/*.{test,spec}.{ts,tsx}"],
  },
});
