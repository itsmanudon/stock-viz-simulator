/**
 * Heikin-Ashi candles (A3.1, M2.3), derived in the browser from stored bars.
 *
 * The standard definition:
 *
 * - close = (open + high + low + close) / 4
 * - open  = (previous HA open + previous HA close) / 2; the first bar's is
 *   (open + close) / 2
 * - high  = max(high, HA open, HA close)
 * - low   = min(low, HA open, HA close)
 *
 * The result is a smoothing, not a price anyone traded at, so the chart labels
 * it "Heikin-Ashi (derived)" and the legend keeps reading the stored bar.
 */

export type Ohlc<T = unknown> = { time: T; open: number; high: number; low: number; close: number };

export function heikinAshi<T>(bars: readonly Ohlc<T>[]): Ohlc<T>[] {
  const out: Ohlc<T>[] = [];
  for (const [i, bar] of bars.entries()) {
    const close = (bar.open + bar.high + bar.low + bar.close) / 4;
    const previous = out[i - 1];
    const open = previous ? (previous.open + previous.close) / 2 : (bar.open + bar.close) / 2;
    out.push({
      time: bar.time,
      open,
      high: Math.max(bar.high, open, close),
      low: Math.min(bar.low, open, close),
      close,
    });
  }
  return out;
}
