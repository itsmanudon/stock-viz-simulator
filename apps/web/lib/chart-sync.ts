/**
 * A6.8 (M2.10): which bar of a chart a linked crosshair time lands on.
 *
 * Panes of the chart workspace that show the same symbol share the crosshair
 * time, each at its own interval. Bar times are UTC seconds as the chart
 * draws them (`barTimeToUtcSeconds`):
 *
 * - **Intraday and daily** bars are stamped at their start (a minute bar's
 *   open, a daily bar's session date), so a time lands on the last bar that
 *   starts at or before it. A daily chart under a 15-minute crosshair shows
 *   that session; a 5-minute chart under a daily one shows the session's
 *   first bar.
 * - **Weekly and monthly** bars are stamped at their period's last stored
 *   session, so a time lands on the first bar stamped on or after its day.
 *
 * A time before the first bar, or (weekly, monthly) after the last bar's
 * period, lands nowhere (null): the crosshair is cleared rather than drawn on
 * a bar that does not hold that time.
 */

const DAY_SECONDS = 86_400;

/** The index of the bar `time` falls in, or null. `times` ascend. */
export function syncedBarIndex(
  times: readonly number[],
  time: number,
  interval: string,
): number | null {
  if (!times.length || !Number.isFinite(time)) return null;
  if (interval === "1wk" || interval === "1mo") {
    const day = Math.floor(time / DAY_SECONDS) * DAY_SECONDS;
    const i = lowerBound(times, day);
    return i < times.length ? i : null;
  }
  if (time < times[0]) return null;
  // The last bar starting at or before `time`.
  return lowerBound(times, time + 1) - 1;
}

/** The first index whose value is >= `value` (times.length if none). */
function lowerBound(times: readonly number[], value: number): number {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
