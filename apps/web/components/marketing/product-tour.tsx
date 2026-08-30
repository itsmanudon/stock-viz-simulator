/**
 * Product tour — the replacement for the old 3x2 icon-and-paragraph grid.
 *
 * Fetches the four public surfaces in parallel and hands the rendered panels
 * to a client tab shell. Each tab is independent: a surface that fails or has
 * no data is dropped rather than shown empty, and if fewer than two survive
 * the whole section renders nothing. A landing page with a broken tour is
 * worse than a landing page without one.
 */

import { Reveal } from "@/components/marketing/reveal";
import {
  ResearchPanel,
  ScreenPanel,
  SimulatePanel,
  TrackPanel,
} from "@/components/marketing/tour-panels";
import { type TourTab, TourTabs } from "@/components/marketing/tour-tabs";
import { ApiError, getBars, getRecommendations, runBacktest, screenSymbols } from "@/lib/api";
import { getLeaderboard } from "@/lib/api/leaderboard";
import type { LeaderboardEntry } from "@/lib/api/leaderboard";
import type { BacktestResult, Recommendation, ScreenerResult } from "@/lib/api/types";

// HDFCBANK.NS: deep (1996-) and *fresh* daily history with no split or bonus
// in the window, so the demo equity curve is continuous and current. A
// recently-split US mega-cap (AAPL 4:1, NVDA 10:1) draws a cliff; the US
// backfill CSVs also stop months short of the NSE series.
const BACKTEST_TICKER = "HDFCBANK.NS";

/**
 * These panels are the same canned queries for every visitor and the data
 * behind them moves once a day, so they go through the Next data cache rather
 * than hitting the API on every landing-page render.
 *
 * The backtest itself is a POST, which Next does not cache — its 400-bar
 * `getBars` call is cached, but the simulation re-runs per render.
 */
const CACHE_S = 3600;
const ROWS = 6;

/** Any API failure collapses to `null` so one dead surface can't take the page down. */
async function safe<T>(run: () => Promise<T>): Promise<T | null> {
  try {
    return await run();
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}

/**
 * The backtest window is derived from the bars actually stored rather than
 * from today's date — a database that hasn't ingested in a while would
 * otherwise get an empty range and no curve.
 */
async function loadBacktest(): Promise<BacktestResult | null> {
  const bars = await safe(() => getBars(BACKTEST_TICKER, { limit: 400 }));
  if (!bars || bars.length < 60) return null;

  const from = bars[0].ts.slice(0, 10);
  const to = bars[bars.length - 1].ts.slice(0, 10);

  const result = await safe(() =>
    runBacktest({
      ticker: BACKTEST_TICKER,
      from,
      to,
      initial_cash: "100000",
      strategy: { type: "sma_crossover", short_window: 20, long_window: 50 },
    }),
  );
  if (!result || result.equity_curve.length < 2) return null;
  return result;
}

export async function ProductTour() {
  const [screen, recs, backtest, leaders] = await Promise.all([
    safe<ScreenerResult[]>(() => screenSymbols({ momentumDays: 30, revalidateSeconds: CACHE_S })),
    safe<Recommendation[]>(() => getRecommendations({ limit: 5, revalidateSeconds: CACHE_S })),
    loadBacktest(),
    safe<LeaderboardEntry[]>(() => getLeaderboard(CACHE_S)),
  ]);

  // The first recommendation that actually carries a vote breakdown — the
  // votes are the whole point of that panel.
  const rec = recs?.find((r) => r.votes.length > 0) ?? null;

  const tabs: TourTab[] = [];
  if (screen && screen.length > 0) {
    tabs.push({
      id: "screen",
      label: "Screen",
      panel: <ScreenPanel rows={screen.slice(0, ROWS)} />,
    });
  }
  if (rec) {
    tabs.push({ id: "research", label: "Research", panel: <ResearchPanel rec={rec} /> });
  }
  if (backtest) {
    tabs.push({ id: "simulate", label: "Simulate", panel: <SimulatePanel result={backtest} /> });
  }
  if (leaders && leaders.length > 0) {
    tabs.push({
      id: "track",
      label: "Track",
      panel: <TrackPanel rows={leaders.slice(0, ROWS)} />,
    });
  }

  if (tabs.length < 2) return null;

  return (
    <section
      aria-labelledby="tour-heading"
      className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24"
    >
      <Reveal className="max-w-2xl">
        <p className="font-mono text-2xs tracking-[0.16em] text-brand uppercase">A session</p>
        <h2
          id="tour-heading"
          className="mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
        >
          The whole loop, <span className="text-text-secondary">not just the chart</span>
        </h2>
      </Reveal>

      <Reveal className="mt-9" delay={80}>
        <TourTabs tabs={tabs} />
      </Reveal>

      <p className="mt-4 font-mono text-2xs text-text-tertiary">
        Live from the public API — the same endpoints the workspace runs on.
      </p>
    </section>
  );
}
