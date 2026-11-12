/**
 * "Watch it work": one row per feature, each with its own animation drawn
 * from the public API (motion batch 1, owner approved 12 Nov 2026).
 *
 * - Backtest: ghost runs around a real stored backtest.
 * - Screener: the sieve, with each layer's count from a real screener query.
 * - Replay: fog over stored daily closes.
 * - Order fill: a receipt priced at a real stored close.
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
import { PrintStamp } from "@/components/marketing/proofs/print-stamp";
import { Sieve, type SieveChip } from "@/components/marketing/proofs/sieve";
import { ApiError, getBars, listSymbols, runBacktest, screenSymbols } from "@/lib/api";
import type { Bar } from "@/lib/api/types";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export type ProofKey = "backtest" | "screener" | "replay" | "fill";

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
  const [backtest, screener, bars] = await Promise.all([
    want.has("backtest") ? loadBacktest().catch(() => null) : null,
    want.has("screener") ? loadScreener() : null,
    want.has("replay") || want.has("fill") ? loadBars() : null,
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
