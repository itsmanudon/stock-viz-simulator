/** A7.14 (M6.1, M6.3): India index options summaries from the owner's local files. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type FoIndia = components["schemas"]["FoIndiaOut"];
export type FoUnderlying = components["schemas"]["FoUnderlyingOut"];

export function getFoIndia(): Promise<FoIndia> {
  return apiGet<FoIndia>("/v1/fo/india", { revalidateSeconds: 3600, tags: ["fo"] });
}
