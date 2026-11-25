/**
 * Setups (A2.2): saved rules with immutable versions. `listPresets` is a
 * public read (the screener's preset picker works signed out); everything
 * else is per user and goes through the server-only authed client, so this
 * module's authed calls must only run on the server (server components and
 * actions).
 */

import { apiGet } from "./client";
import type { components } from "./schema";

export type Setup = components["schemas"]["SetupOut"];
export type SetupDetail = components["schemas"]["SetupDetailOut"];
export type SetupVersion = components["schemas"]["SetupVersionOut"];
export type SetupKind = Setup["kind"];

/** The read-only system setups, newest version each. */
export function listPresets(): Promise<Setup[]> {
  return apiGet<Setup[]>("/v1/setups/presets", { revalidateSeconds: 3600 });
}
