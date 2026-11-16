import { defineConfig, devices } from "@playwright/test";

/**
 * Captures /docs screenshots from a running local stack:
 *   PLAYWRIGHT_BASE_URL=http://localhost:3200 pnpm exec playwright test -c playwright.docs.config.ts
 * Not part of `pnpm e2e` or CI; the images it writes are committed.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests/docs-capture",
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL, ...devices["Desktop Chrome"] },
  webServer: {
    command: process.env.PLAYWRIGHT_WEB_COMMAND ?? "pnpm start",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
