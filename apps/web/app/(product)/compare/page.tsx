/**
 * /compare?tickers=AAPL,MSFT,... — normalized comparison over a shared window.
 *
 * Server component: loads bars in parallel, optionally joins screener metrics,
 * and derives window statistics. Symbol picking and the chart are client islands.
 */

import Link from "next/link";

import { CompareChart } from "@/components/compare-chart";
import { CompareInsights, CompareMetricsTable } from "@/components/compare-metrics";
import { CompareSymbolPicker } from "@/components/compare-symbol-picker";
import { PageFrame } from "@/components/page-frame";
import {
  ResearchEmptyState,
  ResearchPageHeader,
  ResearchSectionHeader,
  ResearchSubnav,
} from "@/components/research-page-header";
import { ApiError, type Bar, getBars, getSymbol, listSymbols, screenSymbols } from "@/lib/api";
import type { ScreenerResult } from "@/lib/api/types";
import { listWatchlist } from "@/lib/api/watchlist";
import {
  type CompareMetrics,
  SAMPLE_COMPARE_TICKERS,
  annualizedVolatilityPct,
  buildCompareHref,
  closesFromBars,
  compareTimeframeDays,
  deriveCompareInsights,
  maxDrawdownPct,
  parseCompareSearchParams,
  rangeReturnPct,
  seriesColor,
  week52PositionPct,
} from "@/lib/compare-workspace";

async function loadSeries(
  ticker: string,
  days: number,
): Promise<{
  ticker: string;
  name: string;
  sector: string | null;
  bars: Bar[];
}> {
  try {
    const [symbol, bars] = await Promise.all([getSymbol(ticker), getBars(ticker, { limit: days })]);
    return { ticker, name: symbol.name, sector: symbol.sector, bars };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ticker, name: ticker, sector: null, bars: [] };
    }
    throw err;
  }
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ tickers?: string; symbols?: string; tf?: string }>;
}) {
  const params = await searchParams;
  const { tickers, timeframe } = parseCompareSearchParams(params);
  const days = compareTimeframeDays(timeframe);
  const sampleHref = buildCompareHref([...SAMPLE_COMPARE_TICKERS], timeframe);

  const universePromise = listSymbols().catch(() => []);
  const screenPromise = tickers.length
    ? screenSymbols().catch(() => [] as ScreenerResult[])
    : Promise.resolve([] as ScreenerResult[]);
  // Guests have no session — the authed call throws and collapses to an empty
  // list, which just hides the quick-add row.
  const watchlistPromise = listWatchlist().catch(() => []);

  const [universe, screenRows, seriesByTicker, watchlist] = await Promise.all([
    universePromise,
    screenPromise,
    tickers.length
      ? Promise.all(tickers.map((ticker) => loadSeries(ticker, days)))
      : Promise.resolve([]),
    watchlistPromise,
  ]);
  const watchlistTickers = watchlist.map((item) => item.ticker);

  const screenByTicker = new Map(screenRows.map((row) => [row.ticker, row]));
  const names: Record<string, string> = {};
  for (const symbol of universe) names[symbol.ticker] = symbol.name;
  for (const row of seriesByTicker) names[row.ticker] = row.name;

  const metrics: CompareMetrics[] = seriesByTicker.map((row, index) => {
    const closes = closesFromBars(row.bars);
    const lastPrice = closes.length ? closes[closes.length - 1] : null;
    const screen = screenByTicker.get(row.ticker);
    const high52 = screen ? Number(screen.high_52w) : null;
    const low52 = screen ? Number(screen.low_52w) : null;
    return {
      ticker: row.ticker,
      name: row.name,
      sector: row.sector ?? screen?.sector ?? null,
      color: seriesColor(index),
      bars: row.bars,
      lastPrice,
      returnPct: rangeReturnPct(closes),
      volatilityPct: annualizedVolatilityPct(closes),
      maxDrawdownPct: maxDrawdownPct(closes),
      rsi14: screen?.rsi_14 ?? null,
      week52PositionPct: week52PositionPct(
        lastPrice,
        low52 !== null && Number.isFinite(low52) ? low52 : null,
        high52 !== null && Number.isFinite(high52) ? high52 : null,
      ),
      sentiment7d: screen?.sentiment_7d ?? null,
    };
  });
  const insights = deriveCompareInsights(metrics);

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <ResearchPageHeader
        title="Compare"
        description="How do these assets compare over the selected period? Series are rebased to 100 at the first stored close in the window."
        actions={
          <nav aria-label="Comparison window" className="flex gap-1">
            {(["1M", "3M", "6M", "1Y", "5Y"] as const).map((value) => (
              <Link
                key={value}
                href={buildCompareHref(tickers, value)}
                className={`rounded-sm border px-2.5 py-1 text-xs transition-colors hover:bg-surface-hover ${
                  timeframe === value
                    ? "border-brand text-foreground"
                    : "border-border-muted text-text-tertiary"
                }`}
              >
                {value}
              </Link>
            ))}
          </nav>
        }
      />
      <ResearchSubnav current="/compare" />

      <div className="mt-5 space-y-7">
        <CompareSymbolPicker
          tickers={tickers}
          timeframe={timeframe}
          names={names}
          watchlistTickers={watchlistTickers}
        />

        {tickers.length === 0 ? (
          <ResearchEmptyState
            title="Select symbols to compare"
            action={
              <Link
                href={sampleHref}
                className="inline-flex h-9 items-center rounded-sm border border-border-muted px-3 text-sm hover:bg-surface-hover"
              >
                Load sample set (AAPL, MSFT, GOOGL, AMZN)
              </Link>
            }
          >
            <p>
              Compare up to six securities on normalized performance, then inspect window return,
              volatility, and any available RSI or sentiment metrics.
            </p>
          </ResearchEmptyState>
        ) : (
          <>
            <section aria-labelledby="compare-chart-heading">
              <ResearchSectionHeader
                id="compare-chart-heading"
                title="Normalized performance"
                description={`${timeframe} window · 100 at the first bar. End-of-day closes only.`}
              />
              <div className="overflow-hidden rounded-md border border-border-muted bg-card p-3 sm:p-4">
                <CompareChart
                  series={metrics.map((row) => ({
                    ticker: row.ticker,
                    bars: row.bars,
                    color: row.color,
                  }))}
                />
              </div>
            </section>

            <section aria-labelledby="compare-metrics-heading">
              <ResearchSectionHeader
                id="compare-metrics-heading"
                title="Comparison metrics"
                description="Window statistics are derived from the loaded closes. RSI, 52-week positioning, and sentiment come from daily metrics when available."
              />
              <CompareMetricsTable rows={metrics} />
            </section>

            <CompareInsights insights={insights} />

            <p className="text-xs text-text-tertiary">
              Open a name in the stock workspace or send it to Backtest from the table links.
            </p>
            <ul className="flex flex-wrap gap-3 text-xs">
              {tickers.map((ticker) => (
                <li key={ticker} className="flex gap-2">
                  <Link href={`/stocks/${ticker}`} className="font-mono hover:underline">
                    {ticker}
                  </Link>
                  <Link
                    href={`/backtest?ticker=${ticker}`}
                    className="text-text-tertiary hover:underline"
                  >
                    Backtest
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </PageFrame>
  );
}
