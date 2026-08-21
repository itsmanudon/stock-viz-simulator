#!/usr/bin/env node
/**
 * Regenerate apps/web/lib/api/schema.d.ts from the API's OpenAPI document.
 *
 * The client's request/response types are hand-written against FastAPI's
 * Pydantic models with nothing checking they still agree. This exports the
 * live schema and generates types from it; `lib/api/schema-check.ts` then
 * asserts the hand-written types are compatible, so drift becomes a `tsc`
 * failure rather than a runtime surprise.
 *
 * Runs the API in-process via uv — no server needs to be listening.
 *
 *   pnpm --filter @stockviz/web gen:api-types
 *
 * CI regenerates and fails if the result differs from what's committed.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const apiDir = join(repoRoot, "apps", "api");
const webDir = join(repoRoot, "apps", "web");
const outFile = join(webDir, "lib", "api", "schema.d.ts");

const scratch = mkdtempSync(join(tmpdir(), "stockviz-openapi-"));
const schemaFile = join(scratch, "openapi.json");

console.log("Exporting OpenAPI schema from the FastAPI app...");
const schema = execFileSync(
  "uv",
  ["--directory", apiDir, "run", "python", "-c", "import json;from stockviz.main import app;print(json.dumps(app.openapi()))"],
  { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 },
);
writeFileSync(schemaFile, schema);

console.log(`Generating ${outFile}...`);
execFileSync("pnpm", ["exec", "openapi-typescript", schemaFile, "-o", outFile], {
  cwd: webDir,
  stdio: "inherit",
});

console.log("Done.");
