/**
 * GET /v1/symbols/{ticker}/volume-profile (A6.7, M2.9): bins, POC and value
 * area over a range, from stored minute bars or (an EOD approximation) daily
 * bars. Public; the chart asks for it through
 * `app/(product)/stocks/[ticker]/chart-tools-actions.ts`. 409 when no profile
 * is offered (an index's volume is not real), with the reason.
 */

import type { VolumeProfile } from "@/lib/volume-profile";
import { apiGet } from "./client";

export function getVolumeProfile(
  ticker: string,
  range: { from: string; to: string; feed?: string | null; bins?: number },
): Promise<VolumeProfile> {
  const q = new URLSearchParams({ from: range.from, to: range.to });
  if (range.feed) q.set("feed", range.feed);
  if (range.bins) q.set("bins", String(range.bins));
  return apiGet<VolumeProfile>(
    `/v1/symbols/${encodeURIComponent(ticker)}/volume-profile?${q.toString()}`,
    { maxAttempts: 1 },
  );
}
