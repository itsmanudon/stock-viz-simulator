/**
 * The starting experiment on /backtest (UI audit F1). The first symbol
 * alphabetically can have no stored bars, and "the last twelve months to
 * today" can fall entirely after the last stored close, so the default run
 * produced nothing. Start on a symbol with history, and end the range at that
 * symbol's own latest close.
 */

export type BacktestSymbol = {
  ticker: string;
  name: string;
  /** `YYYY-MM-DD` of the latest stored close, or null when there is none. */
  lastClose?: string | null;
};

export function pickBacktestTicker(symbols: BacktestSymbol[], requested?: string): string {
  if (requested && symbols.some((symbol) => symbol.ticker === requested)) return requested;
  return (symbols.find((symbol) => symbol.lastClose) ?? symbols[0])?.ticker ?? "";
}

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** One year of stored history, ending at the latest close (or today without one). */
export function defaultBacktestRange(
  lastClose: string | null | undefined,
  today: Date = new Date(),
): { from: string; to: string } {
  const to = lastClose && /^\d{4}-\d{2}-\d{2}$/.test(lastClose) ? lastClose : isoDate(today);
  const start = new Date(`${to}T00:00:00Z`);
  start.setUTCFullYear(start.getUTCFullYear() - 1);
  return { from: isoDate(start), to };
}
