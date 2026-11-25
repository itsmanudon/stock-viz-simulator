/**
 * Data for the "time is the fourth axis" terrain: each tracked symbol's
 * stored closes over the same trailing window, rebased to its first close.
 *
 * Only symbols with a full window are used, so every column of the surface
 * is the same session for every row. Nothing here is invented: a symbol
 * without stored history is simply left out, and with fewer than four
 * complete symbols the section does not render at all.
 */

import { ApiError, getMarketsSummary } from "@/lib/api";
import { formatCloseDate } from "@/lib/stock-workspace";

export type TerrainData = {
  tickers: string[];
  /** Percent change from the window's first close, per symbol per session. */
  series: number[][];
  sessions: number;
  /** The newest stored close date in the window, formatted. */
  lastDate: string | null;
};

export const TERRAIN_SESSIONS = 120;
const MAX_SYMBOLS = 28;

export async function loadTerrain(): Promise<TerrainData | null> {
  try {
    const summary = await getMarketsSummary({ sparklineDays: TERRAIN_SESSIONS });
    const full = summary.rows
      .map((row) => ({
        ticker: row.ticker,
        closes: row.closes.map(Number).filter((n) => Number.isFinite(n) && n > 0),
        at: row.last_close_at,
      }))
      .filter((row) => row.closes.length === TERRAIN_SESSIONS);
    const newest = full
      .map((row) => row.at)
      .filter((at): at is string => Boolean(at))
      .sort()
      .at(-1);
    // Same last session for every row, so each column is one shared date.
    const aligned = full.filter((row) => row.at === newest);
    if (aligned.length < 4) return null;

    const rebased = aligned.slice(0, MAX_SYMBOLS).map((row) => {
      const base = row.closes[0];
      return {
        ticker: row.ticker,
        series: row.closes.map((c) => Number((((c - base) / base) * 100).toFixed(2))),
      };
    });
    // Order rows by where they ended, so the surface reads as one ridge from
    // the window's biggest loser to its biggest gainer.
    rebased.sort((a, b) => (a.series.at(-1) ?? 0) - (b.series.at(-1) ?? 0));

    return {
      tickers: rebased.map((r) => r.ticker),
      series: rebased.map((r) => r.series),
      sessions: TERRAIN_SESSIONS,
      lastDate: formatCloseDate(newest),
    };
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}
