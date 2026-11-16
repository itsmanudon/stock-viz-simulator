/** Headlines the dashboard news card shows. */
export const DASHBOARD_NEWS_LIMIT = 5;

/** The dashboard's news symbols: holdings, then watchlist symbols, each once. */
export function dashboardNewsTickers(
  positions: readonly { ticker: string }[],
  watchlist: readonly { ticker: string }[] | null,
): string[] {
  const tickers = [...positions, ...(watchlist ?? [])].map((row) => row.ticker.toUpperCase());
  return [...new Set(tickers)];
}
