/**
 * Cross-timeframe anchors (A3.2): a drawing's anchor is a daily bar's date
 * and a price, never a pixel, so it lands on the same dates on every
 * interval.
 *
 * The rule, the same periods as the API's resampler
 * (`services/bars/resample.py`): a week is the ISO week (Monday to Sunday), a
 * month the calendar month, by the bar's venue date. On a weekly or monthly
 * chart an anchor maps to the bar whose period contains its date, and sits at
 * that bar's time (the period's last stored session: the Thursday of a week
 * whose Friday was a holiday). On a daily chart it is the bar of that date.
 * A date with no bar of its own (a typed weekend, a gap) sits between its
 * neighbours, interpolated in time; before the first or after the last loaded
 * bar it is extrapolated at the chart's average bar spacing.
 */

import type { StockInterval } from "@/lib/stock-workspace";

const DAY_MS = 86_400_000;

/** "YYYY-MM-DD" (or an API bar timestamp) -> epoch ms of that date at UTC midnight. */
export function dateMs(value: string): number {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Epoch ms -> "YYYY-MM-DD" (UTC). */
export function msToDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** A bar timestamp's calendar date, read from the string. */
export function barDate(ts: string): string {
  return ts.slice(0, 10);
}

/** Monday of the date's ISO week, the first of its month, or the date itself. */
export function periodKey(date: string, interval: StockInterval): string {
  if (interval === "1mo") return `${date.slice(0, 7)}-01`;
  if (interval === "1wk") {
    const ms = dateMs(date);
    const weekday = (new Date(ms).getUTCDay() + 6) % 7; // Monday = 0
    return msToDate(ms - weekday * DAY_MS);
  }
  return date.slice(0, 10);
}

/**
 * The bar an anchor date maps to: its index in `barDates` (oldest first) and
 * that bar's date, or null when no loaded bar's period contains the date.
 */
export function anchorBar(
  date: string,
  interval: StockInterval,
  barDates: readonly string[],
): { index: number; date: string } | null {
  const key = periodKey(date, interval);
  // Binary search on the period keys, which rise with the bars.
  let lo = 0;
  let hi = barDates.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const midKey = periodKey(barDates[mid], interval);
    if (midKey === key) return { index: mid, date: barDates[mid] };
    if (midKey < key) lo = mid + 1;
    else hi = mid - 1;
  }
  return null;
}

/** The bar time (date) an anchor lands on for an interval, or null. */
export function anchorBarTime(
  date: string,
  interval: StockInterval,
  barDates: readonly string[],
): string | null {
  return anchorBar(date, interval, barDates)?.date ?? null;
}

/**
 * The chart's logical index (bar position, fractional between bars) of an
 * anchor date. Null only with no bars.
 */
export function anchorLogical(
  date: string,
  interval: StockInterval,
  barDates: readonly string[],
): number | null {
  const n = barDates.length;
  if (n === 0) return null;
  const hit = anchorBar(date, interval, barDates);
  if (hit) return hit.index;
  const t = dateMs(date);
  const first = dateMs(barDates[0]);
  const last = dateMs(barDates[n - 1]);
  const spacing = n > 1 ? (last - first) / (n - 1) : DAY_MS;
  if (t < first) return (t - first) / spacing;
  if (t > last) return n - 1 + (t - last) / spacing;
  // Between two bars: interpolate in time.
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (dateMs(barDates[mid]) <= t) lo = mid;
    else hi = mid;
  }
  const a = dateMs(barDates[lo]);
  const b = dateMs(barDates[hi]);
  return lo + (b === a ? 0 : (t - a) / (b - a));
}

/**
 * The anchor date a chart position places: the bar under it, clamped to the
 * loaded bars (anchors are never in the future). On weekly and monthly charts
 * that is the period's last stored session, which maps back to the same bar.
 */
export function logicalToDate(logical: number, barDates: readonly string[]): string | null {
  if (barDates.length === 0) return null;
  const index = Math.max(0, Math.min(barDates.length - 1, Math.round(logical)));
  return barDates[index];
}
