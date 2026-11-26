"use server";

/**
 * A3.3: what the chart's anchored VWAPs read, through the web server (which
 * carries the rate-limit exemption): the series for one drawing, and the
 * symbol's last earnings date for the "Anchor at last earnings" shortcut.
 */

import { type Avwap, getAvwap } from "@/lib/api/avwap";
import { getEarningsCalendar } from "@/lib/api/earnings";
import type { StockInterval } from "@/lib/stock-workspace";

export async function avwapAction(
  ticker: string,
  anchor: string,
  interval: StockInterval,
  bands: number,
): Promise<{ avwap?: Avwap; error?: string }> {
  try {
    return { avwap: await getAvwap(ticker, anchor, interval, bands) };
  } catch {
    return { error: "The anchored VWAP could not be loaded." };
  }
}

/** The newest earnings date on or before `last` within the stored bars, or null. */
export async function lastEarningsDateAction(
  ticker: string,
  first: string,
  last: string,
): Promise<{ date: string | null; error?: string }> {
  try {
    const events = await getEarningsCalendar({ from: first, to: last });
    const dates = events
      .filter((e) => e.ticker.toUpperCase() === ticker.toUpperCase())
      .map((e) => String(e.event_date).slice(0, 10))
      .filter((d) => d >= first && d <= last)
      .sort();
    return { date: dates.at(-1) ?? null };
  } catch {
    return { date: null, error: "Earnings dates could not be loaded." };
  }
}
