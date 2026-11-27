/** A9.7 (M1.10, M3.5): stored FRED series and the spreads built from them. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type MacroOverview = components["schemas"]["MacroOverviewOut"];
export type MacroSeries = components["schemas"]["MacroSeriesOut"];
export type MacroSpread = components["schemas"]["MacroSpreadOut"];
export type MacroPoint = components["schemas"]["MacroPointOut"];

export function getMacroOverview(): Promise<MacroOverview> {
  return apiGet<MacroOverview>("/v1/macro", { revalidateSeconds: 3600, tags: ["macro"] });
}
