/**
 * "Watch it work": one row per feature, each with its own animation drawn
 * from the public API (motion batch 1, owner approved 12 Nov 2026).
 *
 * - Backtest: ghost runs around a real stored backtest.
 * - Screener: the sieve, with each layer's count from a real screener query.
 * - Replay: fog over stored daily closes.
 * - Order fill: a receipt priced at a real stored close.
 *
 * Batch 2 adds:
 * - Compare: two symbols in two currencies spring onto one index.
 * - Signals: a sonar sweep over real Signals rows.
 * - Portfolio: an example account's split, drifting with real closes.
 *
 * Every row states its figures in text beside the animation, so the canvas is
 * decoration (aria-hidden) and the page reads the same without it. A row whose
 * data is missing is left out; with no rows the section renders nothing.
 */

import { ArrowRight } from "lucide-react";
import { unstable_cache } from "next/cache";
import Link from "next/link";
import type { ReactNode } from "react";

import { FogReplay } from "@/components/marketing/proofs/fog-replay";
import { GhostRuns } from "@/components/marketing/proofs/ghost-runs";
import { type Drop, LiquidAllocation } from "@/components/marketing/proofs/liquid-allocation";
import { LoupeChart } from "@/components/marketing/proofs/loupe-chart";
import { PrintStamp } from "@/components/marketing/proofs/print-stamp";
import { type RebaseSeries, RebaseSnap } from "@/components/marketing/proofs/rebase-snap";
import { Sieve, type SieveChip } from "@/components/marketing/proofs/sieve";
import { type SonarBlip, SonarSweep } from "@/components/marketing/proofs/sonar-sweep";
import {
  ApiError,
  getBars,
  getRecommendations,
  listSymbols,
  runBacktest,
  screenSymbols,
} from "@/lib/api";
import type { Bar } from "@/lib/api/types";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export type ProofKey =
  | "backtest"
  | "screener"
  | "replay"
  | "fill"
  | "compare"
  | "signals"
  | "portfolio"
  | "chart";

const CACHE_S = 3600;
/** Liquid, long-history symbols first; the first with enough stored bars wins. */
const CANDIDATES = ["AAPL", "NVDA", "MSFT", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"];
const STRATEGY = { type: "sma_crossover", short_window: 20, long_window: 50 } as const;

async function safe<T>(run: () => Promise<T>): Promise<T | null> {
  try {
    return await run();
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}

async function firstBars(
  limit: number,
  min: number,
): Promise<{ ticker: string; bars: Bar[] } | null> {
  for (const ticker of CANDIDATES) {
    const bars = await safe(() => getBars(ticker, { limit }));
    if (bars && bars.length >= min) return { ticker, bars };
  }
  return null;
}

type BacktestProof = {
  ticker: string;
  from: string;
  to: string;
  strategy: number[];
  benchmark: number[];
  totalReturn: number;
  benchmarkReturn: number;
};

/**
 * One backtest for every visitor, cached for an hour. The run is a POST, which
 * the fetch cache does not keep, so the whole result is cached instead.
 */
const loadBacktest = unstable_cache(
  async (): Promise<BacktestProof | null> => {
    const found = await firstBars(400, 120);
    if (!found) return null;
    const { ticker, bars } = found;
    const from = bars[0].ts.slice(0, 10);
    const to = bars[bars.length - 1].ts.slice(0, 10);
    const result = await safe(() =>
      runBacktest({ ticker, from, to, initial_cash: "100000", strategy: STRATEGY }),
    );
    if (!result || result.equity_curve.length < 30) return null;
    const closeByDay = new Map(bars.map((bar) => [bar.ts.slice(0, 10), Number(bar.close)]));
    const strategy: number[] = [];
    const benchmark: number[] = [];
    for (const point of result.equity_curve) {
      const close = closeByDay.get(point.date.slice(0, 10));
      if (close === undefined) continue;
      strategy.push(Number(point.nav));
      benchmark.push(close);
    }
    if (strategy.length < 30) return null;
    return {
      ticker,
      from,
      to,
      strategy,
      benchmark,
      totalReturn: result.summary.total_return,
      benchmarkReturn: result.summary.benchmark_return,
    };
  },
  ["landing-proof-backtest"],
  { revalidate: CACHE_S, tags: ["bars"] },
);

type ScreenerProof = {
  layers: string[];
  chips: SieveChip[];
  counts: number[];
  asOf: string | null;
};

/**
 * Three cumulative screener queries. Each layer's survivors are exactly what
 * the screener returns with that layer's filters added, so the counts in the
 * picture are the screener's own.
 */
async function loadScreener(): Promise<ScreenerProof | null> {
  const steps = [
    { label: "RSI between 30 and 70", params: { rsiMin: 30, rsiMax: 70 } },
    {
      label: "Up over 30 days",
      params: { rsiMin: 30, rsiMax: 70, momentumDays: 30, momentumMin: 0 },
    },
    {
      label: "Near its 52-week high",
      params: { rsiMin: 30, rsiMax: 70, momentumDays: 30, momentumMin: 0, near52wHigh: true },
    },
  ];
  const [all, ...layered] = await Promise.all([
    safe(() => screenSymbols({ revalidateSeconds: CACHE_S })),
    ...steps.map((step) =>
      safe(() => screenSymbols({ ...step.params, revalidateSeconds: CACHE_S })),
    ),
  ]);
  if (!all || all.length < 6) return null;
  const sets = layered.map((rows) => new Set((rows ?? []).map((row) => row.ticker)));
  // Keep layers while something still gets through; a layer that stops every
  // symbol would end the picture on an empty floor.
  let depth = 0;
  while (depth < steps.length && layered[depth] && sets[depth].size > 0) depth++;
  if (depth === 0) return null;
  const used = sets.slice(0, depth);
  const chips = all.slice(0, 48).map((row) => {
    const stop = used.findIndex((set) => !set.has(row.ticker));
    return { ticker: row.ticker, stopsAt: stop === -1 ? depth : stop };
  });
  return {
    layers: steps.slice(0, depth).map((step) => step.label),
    chips,
    counts: [chips.length, ...used.map((_, i) => chips.filter((c) => c.stopsAt > i).length)],
    asOf: all.find((row) => row.as_of)?.as_of ?? null,
  };
}

type BarsProof = { ticker: string; bars: Bar[]; currency: string };

async function loadBars(): Promise<BarsProof | null> {
  const [found, symbols] = await Promise.all([firstBars(120, 40), safe(() => listSymbols())]);
  if (!found) return null;
  const currency = symbols?.find((s) => s.ticker === found.ticker)?.currency ?? "USD";
  return { ...found, currency };
}

/** Currency symbol for a label on a price axis; other currencies use the code. */
function currencyMark(currency: string) {
  return currency === "USD" ? "$" : currency === "INR" ? "₹" : `${currency} `;
}

type CompareProof = {
  a: RebaseSeries;
  b: RebaseSeries;
  from: string;
  to: string;
  /** The two symbols trade in different currencies. */
  mixed: boolean;
};

/**
 * A US and an Indian listing over the trading days both have stored; failing
 * that, two US symbols at very different price levels.
 */
async function loadCompare(): Promise<CompareProof | null> {
  const pairs = [
    ["AAPL", "RELIANCE.NS"],
    ["MSFT", "TCS.NS"],
    ["NVDA", "HDFCBANK.NS"],
    ["MSFT", "KO"],
    ["AAPL", "KO"],
  ] as const;
  const symbols = await safe(() => listSymbols());
  const currencyOf = (t: string) => symbols?.find((s) => s.ticker === t)?.currency ?? "USD";
  for (const [x, y] of pairs) {
    const [bx, by] = await Promise.all([
      safe(() => getBars(x, { limit: 160 })),
      safe(() => getBars(y, { limit: 160 })),
    ]);
    if (!bx || !by) continue;
    const yByDay = new Map(by.map((bar) => [bar.ts.slice(0, 10), Number(bar.close)]));
    const days: string[] = [];
    const ax: number[] = [];
    const ay: number[] = [];
    for (const bar of bx) {
      const day = bar.ts.slice(0, 10);
      const other = yByDay.get(day);
      if (other === undefined) continue;
      days.push(day);
      ax.push(Number(bar.close));
      ay.push(other);
    }
    if (days.length < 40) continue;
    return {
      a: { ticker: x, symbol: currencyMark(currencyOf(x)), closes: ax },
      b: { ticker: y, symbol: currencyMark(currencyOf(y)), closes: ay },
      from: days[0],
      to: days[days.length - 1],
      mixed: currencyOf(x) !== currencyOf(y),
    };
  }
  return null;
}

type SignalsProof = { blips: SonarBlip[]; computedAt: string | null };

async function loadSignals(): Promise<SignalsProof | null> {
  const rows = await safe(() => getRecommendations({ limit: 10, revalidateSeconds: CACHE_S }));
  const usable = (rows ?? []).filter((row) => row.max_score > 0);
  if (usable.length < 3) return null;
  return {
    blips: usable.map((row) => ({ ticker: row.ticker, score: row.score, max: row.max_score })),
    computedAt: usable[0].computed_at,
  };
}

type PortfolioProof = {
  drops: Drop[];
  cash: { start: number; now: number };
  from: string;
  to: string;
  value: number;
};

const EXAMPLE_TICKERS = ["AAPL", "NVDA", "MSFT", "JPM", "KO", "AMZN", "GOOGL", "XOM"];
const EXAMPLE_CASH = 20_000;
const EXAMPLE_EACH = 16_000;
const EXAMPLE_LOOKBACK = 60;

/**
 * An example $100,000 account: $16,000 in each of five US symbols at the
 * close 60 trading days back, $20,000 left in cash. Each holding is valued
 * at the latest close both dates share, so the drift is real price movement.
 */
async function loadPortfolio(): Promise<PortfolioProof | null> {
  const series = await Promise.all(
    EXAMPLE_TICKERS.map(async (ticker) => ({
      ticker,
      bars: await safe(() => getBars(ticker, { limit: EXAMPLE_LOOKBACK + 10 })),
    })),
  );
  const first = series.find((s) => s.bars && s.bars.length > EXAMPLE_LOOKBACK);
  if (!first?.bars) return null;
  const from = first.bars[first.bars.length - 1 - EXAMPLE_LOOKBACK].ts.slice(0, 10);
  const to = first.bars[first.bars.length - 1].ts.slice(0, 10);
  const held: { ticker: string; start: number; now: number }[] = [];
  for (const s of series) {
    if (!s.bars || held.length === 5) continue;
    const close = (day: string) => s.bars?.find((bar) => bar.ts.slice(0, 10) === day)?.close;
    const start = close(from);
    const now = close(to);
    if (start === undefined || now === undefined) continue;
    held.push({
      ticker: s.ticker,
      start: EXAMPLE_EACH,
      now: (EXAMPLE_EACH * Number(now)) / Number(start),
    });
  }
  if (held.length < 3) return null;
  const startTotal = EXAMPLE_CASH + EXAMPLE_EACH * held.length;
  const nowTotal = EXAMPLE_CASH + held.reduce((sum, h) => sum + h.now, 0);
  return {
    drops: held.map((h) => ({
      ticker: h.ticker,
      start: h.start / startTotal,
      now: h.now / nowTotal,
    })),
    cash: { start: EXAMPLE_CASH / startTotal, now: EXAMPLE_CASH / nowTotal },
    from,
    to,
    value: nowTotal,
  };
}

function fmtReturn(fraction: number) {
  const pct = fraction * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function Row({
  eyebrow,
  title,
  children,
  facts,
  href,
  cta,
  stage,
  flip,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
  facts: ReactNode;
  href: string;
  cta: string;
  stage: ReactNode;
  flip?: boolean;
}) {
  return (
    <li data-motion-item className="grid items-center gap-8 md:grid-cols-2 md:gap-12">
      <div className={cn("grid gap-3", flip && "md:order-2")}>
        <span className="font-mono text-2xs tracking-[0.14em] text-brand uppercase">{eyebrow}</span>
        <h3 className="text-2xl font-medium tracking-[-0.02em] text-balance sm:text-3xl">
          {title}
        </h3>
        <p className="max-w-md text-base leading-7 text-text-secondary text-pretty">{children}</p>
        <p className="font-mono text-xs leading-6 text-text-tertiary">{facts}</p>
        <Link
          href={href}
          className="mt-1 inline-flex w-fit items-center gap-1.5 text-sm font-medium hover:underline"
        >
          {cta}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
      <div className="relative aspect-[16/10] w-full max-w-full overflow-hidden rounded-3xl border border-border-muted bg-card">
        {stage}
      </div>
    </li>
  );
}

export async function ProofSection({
  only = ["backtest", "screener", "replay", "fill"],
}: {
  only?: ProofKey[];
}) {
  const want = new Set(only);
  const [backtest, screener, bars, compare, signals, portfolio] = await Promise.all([
    want.has("backtest") ? loadBacktest().catch(() => null) : null,
    want.has("screener") ? loadScreener() : null,
    want.has("replay") || want.has("fill") || want.has("chart") ? loadBars() : null,
    want.has("compare") ? loadCompare() : null,
    want.has("signals") ? loadSignals() : null,
    want.has("portfolio") ? loadPortfolio() : null,
  ]);

  const rows: ReactNode[] = [];
  for (const key of only) {
    const flip = rows.length % 2 === 1;
    if (key === "backtest" && backtest) {
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Backtest"
          title="Was it skill, or the order of the days?"
          facts={
            <>
              {backtest.ticker}, 20/50-day average crossover, {formatCloseDate(backtest.from)} to{" "}
              {formatCloseDate(backtest.to)}: strategy {fmtReturn(backtest.totalReturn)}, buy and
              hold {fmtReturn(backtest.benchmarkReturn)}.
            </>
          }
          href="/backtest"
          cta="Run a backtest"
          stage={<GhostRuns strategy={backtest.strategy} benchmark={backtest.benchmark} />}
        >
          The faint lines are the same strategy&rsquo;s daily returns, reshuffled 36 times. The
          bright line is what actually happened, beside simply holding the stock.
        </Row>,
      );
    }
    if (key === "screener" && screener) {
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Screener"
          title="From the whole list to a handful."
          facts={
            <>
              {screener.counts.join(" → ")} symbols after {screener.layers.join(" · ")}
              {screener.asOf ? `, as of ${formatCloseDate(screener.asOf)}` : ""}.
            </>
          }
          href="/screener"
          cta="Open the screener"
          stage={<Sieve layers={screener.layers} chips={screener.chips} />}
        >
          Every tracked symbol drops through the filters. The ones that fail a filter fall out; the
          ones left are worth a closer look.
        </Row>,
      );
    }
    if (key === "chart" && bars) {
      const candles = bars.bars.slice(-90).map((bar) => ({
        date: formatCloseDate(bar.ts) ?? "",
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close),
      }));
      const last = candles[candles.length - 1];
      const f = (v: number) => formatCurrency(v, bars.currency);
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Stock page"
          title="Put any day under the glass."
          facts={
            <>
              {bars.ticker}, {candles.length} stored daily bars, {candles[0].date} to {last.date}.
              Latest: open {f(last.open)}, high {f(last.high)}, low {f(last.low)}, close{" "}
              {f(last.close)}.
            </>
          }
          href={`/stocks/${encodeURIComponent(bars.ticker)}`}
          cta={`Open ${bars.ticker}`}
          stage={<LoupeChart bars={candles} />}
        >
          Every candle is one stored trading day. Point at the chart to read that day&rsquo;s open,
          high, low and close.
        </Row>,
      );
    }
    if (key === "replay" && bars) {
      const dates = bars.bars.map((bar) => formatCloseDate(bar.ts) ?? "");
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Replay"
          title="Trade the past without seeing the future."
          facts={
            <>
              {bars.ticker}, {bars.bars.length} stored daily closes, {dates[0]} to{" "}
              {dates[dates.length - 1]}.
            </>
          }
          href="/replay"
          cta="Start a replay"
          stage={<FogReplay closes={bars.bars.map((bar) => Number(bar.close))} dates={dates} />}
        >
          Replay shows bars only up to the day you are on. Make your call, then step forward and see
          what the next days did.
        </Row>,
      );
    }
    if (key === "fill" && bars) {
      const last = bars.bars[bars.bars.length - 1];
      const currency = bars.currency;
      const date = formatCloseDate(last.ts) ?? "";
      const short = date.replace(/,? \d{4}$/, "").toUpperCase();
      const price = Number(last.close);
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Order fill"
          title="Every fill names its close."
          facts={
            <>
              Example: buy 10 {bars.ticker} at the {date} close of {formatCurrency(price, currency)}
              , no fees.
            </>
          }
          href="/product/paper-trading"
          cta="How paper trading works"
          stage={
            <PrintStamp
              heading={`EXAMPLE · BUY 10 ${bars.ticker}`}
              lines={[
                ["Type", "Market"],
                ["Fills at", "Next stored close"],
                ["Close of", date],
                ["Price", formatCurrency(price, currency)],
                ["Fees", "None"],
                ["Total", formatCurrency(price * 10, currency)],
              ]}
              stamp={`FILLED · ${short}`}
            />
          }
        >
          A paper order waits for the next stored daily close and fills at that price. The record
          keeps the close and its date, so you can check it later.
        </Row>,
      );
    }
    if (key === "compare" && compare) {
      const ret = (s: number[]) => fmtReturn(s[s.length - 1] / s[0] - 1);
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Compare"
          title={
            compare.mixed ? "Two currencies, one starting line." : "Two prices, one starting line."
          }
          facts={
            <>
              {compare.a.ticker} {ret(compare.a.closes)} and {compare.b.ticker}{" "}
              {ret(compare.b.closes)}, {formatCloseDate(compare.from)} to{" "}
              {formatCloseDate(compare.to)}, both rebased to 100.
            </>
          }
          href="/compare"
          cta="Compare symbols"
          stage={<RebaseSnap a={compare.a} b={compare.b} />}
        >
          {compare.mixed
            ? "A dollar price and a rupee price can’t share an axis."
            : "Two stocks at very different prices can’t share one price axis."}{" "}
          Compare starts both at 100 on the same day, so the lines show return, not price.
        </Row>,
      );
    }
    if (key === "signals" && signals) {
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Signals"
          title="Seven rules, read on every pass."
          facts={
            <>
              {signals.blips.map((b) => `${b.ticker} ${b.score}/${b.max}`).join(" · ")}
              {signals.computedAt ? `, computed ${formatCloseDate(signals.computedAt)}` : ""}. Not
              investment advice.
            </>
          }
          href="/recommendations"
          cta="Read the signals"
          stage={<SonarSweep blips={signals.blips} />}
        >
          Each symbol is scored by a vote of simple rules you can read one by one. The more rules
          pass, the nearer the centre it sits.
        </Row>,
      );
    }
    if (key === "portfolio" && portfolio) {
      const pct = (v: number) => `${Math.round(v * 100)}%`;
      rows.push(
        <Row
          key={key}
          flip={flip}
          eyebrow="Portfolio"
          title="Watch the split drift."
          facts={
            <>
              Example account: $16,000 each in {portfolio.drops.map((d) => d.ticker).join(", ")} and
              $20,000 cash at the {formatCloseDate(portfolio.from)} close. By{" "}
              {formatCloseDate(portfolio.to)}:{" "}
              {portfolio.drops.map((d) => `${d.ticker} ${pct(d.now)}`).join(", ")}, cash{" "}
              {pct(portfolio.cash.now)}.
            </>
          }
          href="/product/paper-trading"
          cta="Open a paper account"
          stage={
            <LiquidAllocation
              drops={portfolio.drops}
              cash={portfolio.cash}
              startLabel={`Split at the ${formatCloseDate(portfolio.from)} close`}
              nowLabel={`Split at the ${formatCloseDate(portfolio.to)} close`}
            />
          }
        >
          Prices move, so a portfolio&rsquo;s split moves with them. Each drop is a holding, sized
          by its share of the account, around the cash it was bought with.
        </Row>,
      );
    }
  }

  if (rows.length === 0) return null;
  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
      <div className="grid max-w-2xl gap-3">
        <h2
          data-motion="words"
          className="text-3xl font-medium tracking-[-0.03em] text-balance sm:text-4xl lg:text-5xl"
        >
          Watch it work.{" "}
          <span className="text-text-tertiary">Real stored data, nothing staged.</span>
        </h2>
      </div>
      <ul data-motion="rise" className="mt-14 grid gap-20 sm:gap-24">
        {rows}
      </ul>
    </section>
  );
}
