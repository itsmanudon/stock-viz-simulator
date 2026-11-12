/**
 * The last session's breadth, for the market weather background: how many
 * tracked symbols closed up, out of those with a dated move. It uses the
 * same rule as /markets (`change_pct` is null for a stalled symbol, which
 * then does not count), and is dated by the newest stored close.
 */

import { ApiError, getMarketsSummary } from "@/lib/api";
import { formatCloseDate } from "@/lib/stock-workspace";

export type Breadth = { up: number; counted: number; share: number; date: string | null };

export async function loadBreadth(): Promise<Breadth | null> {
  try {
    const summary = await getMarketsSummary({});
    const moving = summary.rows.filter((row) => row.change_pct !== null);
    if (moving.length < 5) return null;
    const up = moving.filter((row) => (row.change_pct ?? 0) > 0).length;
    const newest = moving
      .map((row) => row.last_close_at)
      .filter((at): at is string => Boolean(at))
      .sort()
      .at(-1);
    return {
      up,
      counted: moving.length,
      share: up / moving.length,
      date: formatCloseDate(newest),
    };
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}

/** "18 of 25 tracked symbols closed up on Apr 7, 2025" */
export function describeBreadth(b: Breadth): string {
  return `${b.up} of ${b.counted} tracked symbols closed up${b.date ? ` on ${b.date}` : ""}`;
}
