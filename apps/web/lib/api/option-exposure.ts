/** A7.9 (M6.2): GEX/DEX and key levels from the newest stored US chain. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type OptionExposure = components["schemas"]["OptionExposureOut"];

export function getOptionExposure(ticker: string): Promise<OptionExposure> {
  return apiGet<OptionExposure>(`/v1/options/${encodeURIComponent(ticker)}/exposure`, {
    revalidateSeconds: 3600,
    tags: ["options"],
  });
}
