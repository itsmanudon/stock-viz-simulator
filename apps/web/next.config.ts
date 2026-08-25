import path from "node:path";
import { fileURLToPath } from "node:url";

import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "../..");

const config: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Monorepo: trace files from the repo root so the standalone output
  // includes pnpm-hoisted dependencies instead of assuming apps/web is root.
  outputFileTracingRoot: repoRoot,
  // pnpm's isolated linker leaves @swc/helpers as a nested symlink that
  // standalone tracing often omits; the image then crashes on boot with
  // MODULE_NOT_FOUND for esm/_interop_require_default.js. The Docker build
  // also sets node-linker=hoisted. This include is belt-and-suspenders.
  outputFileTracingIncludes: {
    "*": [
      "../../node_modules/@swc/helpers/**/*",
      "../../node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers/**/*",
    ],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

// Source-map upload is only enabled when SENTRY_AUTH_TOKEN is present
// (i.e. CI/prod builds). Without it, withSentryConfig still wires the SDK
// but skips the upload step — keeping local dev fast and offline-friendly.
const sentryEnabled = Boolean(process.env.SENTRY_AUTH_TOKEN);

export default sentryEnabled
  ? withSentryConfig(config, {
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      authToken: process.env.SENTRY_AUTH_TOKEN,
      silent: !process.env.CI,
      widenClientFileUpload: true,
      tunnelRoute: "/monitoring",
      disableLogger: true,
    })
  : config;
