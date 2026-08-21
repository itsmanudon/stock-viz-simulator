/**
 * Vitest config for the web app's unit tests.
 *
 * Playwright covers whole user journeys against a real stack; these cover the
 * pure logic underneath — formatters, sort comparators, the open-redirect
 * guard, CSV escaping — which Playwright can't reach cheaply and which had no
 * coverage at all.
 *
 * `tests/e2e` is excluded via `include`: those are Playwright specs and would
 * fail if Vitest tried to run them.
 */

import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Vite resolves the `@/*` paths from tsconfig.json natively.
    tsconfigPaths: true,
    alias: {
      // `server-only` throws on import outside a React Server Component.
      // Under Vitest we're testing the module's logic directly, so stub it.
      "server-only": fileURLToPath(new URL("./tests/stubs/server-only.ts", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["lib/**/*.ts", "components/**/*.tsx"],
      exclude: ["**/*.d.ts", "lib/api/types.ts"],
    },
  },
});
