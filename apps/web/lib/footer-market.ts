/**
 * Pure helpers behind the footer's market line and status strip
 * (components/footer-market.tsx). Kept apart so they can be tested without
 * the API.
 */

import type { ServiceStatus } from "@/lib/api/status";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * Equal-weight average of rebased series: for each session, the mean of every
 * symbol's percent change from its own first close. Every series must cover
 * the same sessions (the terrain loader guarantees it). Returns null when
 * there is nothing to average.
 */
export function equalWeightPath(series: number[][]): number[] | null {
  const rows = series.filter((row) => row.length > 1);
  if (!rows.length) return null;
  const length = Math.min(...rows.map((row) => row.length));
  const out: number[] = [];
  for (let i = 0; i < length; i += 1) {
    let sum = 0;
    for (const row of rows) sum += row[i];
    out.push(Number((sum / rows.length).toFixed(2)));
  }
  return out;
}

/** SVG path for a series in a `width` x `height` box, with `pad` above and below. */
export function linePath(values: number[], width: number, height: number, pad = 4): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  return values
    .map((v, i) => {
      const x = (i * step).toFixed(1);
      const y = (pad + (1 - (v - min) / span) * (height - pad * 2)).toFixed(1);
      return `${i ? "L" : "M"}${x} ${y}`;
    })
    .join(" ");
}

/** The y of the last point in the same box, for the end dot. */
export function lastPointY(values: number[], height: number, pad = 4): number {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const last = values[values.length - 1];
  return pad + (1 - (last - min) / span) * (height - pad * 2);
}

/** The markets the product is built around, in the order the strip shows them. */
const MARKET_NAMES: Record<string, string> = { US: "US", IN: "India" };

export type StatusFacts = {
  closes: { market: string; date: string }[];
  /** "ok" when every nightly job's latest run succeeded or was skipped. */
  refresh: "ok" | "issue" | "unknown";
};

/** The strip's facts from `/v1/status`: newest close per market and the nightly state. */
export function statusFacts(status: ServiceStatus | null): StatusFacts {
  if (!status) return { closes: [], refresh: "unknown" };
  const closes = Object.keys(MARKET_NAMES).flatMap((code) => {
    const market = status.markets.find((m) => m.country === code);
    const date = market?.newest_bar ? formatCloseDate(market.newest_bar) : null;
    return date ? [{ market: MARKET_NAMES[code], date }] : [];
  });
  const finished = status.jobs.filter((job) => job.status !== "running");
  const refresh = !finished.length
    ? "unknown"
    : finished.some((job) => job.status === "failed")
      ? "issue"
      : "ok";
  return { closes, refresh };
}
