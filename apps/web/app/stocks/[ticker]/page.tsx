/**
 * /stocks/[ticker] — OHLCV chart + indicators + recent news.
 *
 * Server-rendered shell that fetches everything in parallel: symbol detail,
 * bars for the selected timeframe, the indicator bundle the user toggled on
 * via search params, and the ticker's news. The chart itself is a client
 * component (lightweight-charts needs ``window``).
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { NewsList } from "@/components/news-list";
import { PriceChart } from "@/components/price-chart";
import { WatchlistToggle } from "@/components/watchlist-toggle";
import {
  ApiError,
  type SymbolDetail,
  getBars,
  getIndicators,
  getNewsForTicker,
  getSymbol,
} from "@/lib/api";
import { listWatchlist } from "@/lib/api/watchlist";

const TIMEFRAMES = [
  { value: "1M", days: 22 },
  { value: "3M", days: 65 },
  { value: "6M", days: 130 },
  { value: "1Y", days: 252 },
  { value: "5Y", days: 1260 },
  { value: "MAX", days: 5000 },
] as const;

type Timeframe = (typeof TIMEFRAMES)[number]["value"];

const ALL_INDICATORS = ["sma_20", "sma_50", "sma_200", "ema_50", "rsi_14", "macd"] as const;
type IndicatorName = (typeof ALL_INDICATORS)[number];

function parseTimeframe(raw: string | undefined): Timeframe {
  const valid = TIMEFRAMES.find((t) => t.value === raw)?.value;
  return valid ?? "1Y";
}

function parseIndicators(raw: string | undefined): IndicatorName[] {
  if (!raw) return ["sma_50"];
  const valid = new Set<string>(ALL_INDICATORS);
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter((s): s is IndicatorName => valid.has(s));
}

function fmtPrice(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function toggleHref(
  ticker: string,
  current: IndicatorName[],
  toggle: IndicatorName,
  timeframe: Timeframe,
): string {
  const set = new Set(current);
  if (set.has(toggle)) set.delete(toggle);
  else set.add(toggle);
  const params = new URLSearchParams();
  if (set.size) params.set("indicators", Array.from(set).join(","));
  params.set("tf", timeframe);
  return `/stocks/${ticker}?${params.toString()}`;
}

function timeframeHref(ticker: string, indicators: IndicatorName[], tf: Timeframe): string {
  const params = new URLSearchParams();
  if (indicators.length) params.set("indicators", indicators.join(","));
  params.set("tf", tf);
  return `/stocks/${ticker}?${params.toString()}`;
}

export default async function StockPage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ tf?: string; indicators?: string }>;
}) {
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.toUpperCase();
  const sp = await searchParams;
  const tf = parseTimeframe(sp.tf);
  const indicators = parseIndicators(sp.indicators);
  const tfDays = TIMEFRAMES.find((t) => t.value === tf)?.days ?? 252;

  let symbol: SymbolDetail;
  try {
    symbol = await getSymbol(ticker);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const [bars, indicatorBundle, news, session] = await Promise.all([
    getBars(ticker, { limit: tfDays }),
    indicators.length
      ? getIndicators(ticker, { names: indicators, limit: tfDays })
      : Promise.resolve(null),
    getNewsForTicker(ticker, 8).catch(() => []),
    auth(),
  ]);

  let inWatchlist = false;
  if (session?.user?.id) {
    try {
      const items = await listWatchlist();
      inWatchlist = items.some((i) => i.ticker === ticker);
    } catch {
      // If the watchlist call fails (e.g. token expired), just hide state.
      inWatchlist = false;
    }
  }

  const last = symbol.latest?.close ? Number(symbol.latest.close) : null;
  const firstBarClose = bars.length ? Number(bars[0].close) : null;
  const periodChangePct =
    last !== null && firstBarClose !== null && firstBarClose !== 0
      ? ((last - firstBarClose) / firstBarClose) * 100
      : null;

  const overlaySeries = indicatorBundle
    ? Object.fromEntries(
        Object.entries(indicatorBundle.series).filter(([name]) => name !== "rsi_14"),
      )
    : {};
  const showMacd = indicators.includes("macd");

  return (
    <div className="container mx-auto px-6 py-10">
      <header className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            <span className="font-mono">{symbol.ticker}</span>
            <span className="ml-3 text-base font-normal text-muted-foreground">{symbol.name}</span>
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {symbol.sector ?? "—"} · {symbol.exchange ?? "—"}
          </p>
        </div>
        <div className="flex items-baseline gap-4">
          {session?.user?.id ? (
            <WatchlistToggle ticker={symbol.ticker} initialInWatchlist={inWatchlist} />
          ) : null}
          <div className="text-right font-mono">
            <div className="text-3xl">${fmtPrice(last)}</div>
            <div
              className={`text-sm ${
                periodChangePct === null
                  ? "text-muted-foreground"
                  : periodChangePct >= 0
                    ? "text-green-500"
                    : "text-red-500"
              }`}
            >
              {periodChangePct === null
                ? `${tf}: —`
                : `${tf}: ${periodChangePct >= 0 ? "+" : ""}${periodChangePct.toFixed(2)}%`}
            </div>
          </div>
        </div>
      </header>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <nav className="flex gap-1">
          {TIMEFRAMES.map((t) => (
            <Link
              key={t.value}
              href={timeframeHref(ticker, indicators, t.value)}
              className={`rounded-md border px-2.5 py-1 text-xs transition hover:bg-accent ${
                tf === t.value ? "border-primary text-foreground" : "text-muted-foreground"
              }`}
            >
              {t.value}
            </Link>
          ))}
        </nav>
        <nav className="flex flex-wrap gap-1">
          {ALL_INDICATORS.map((name) => {
            const on = indicators.includes(name);
            return (
              <Link
                key={name}
                href={toggleHref(ticker, indicators, name, tf)}
                className={`rounded-md border px-2.5 py-1 text-xs uppercase transition hover:bg-accent ${
                  on ? "border-primary text-foreground" : "text-muted-foreground"
                }`}
              >
                {name.replace("_", " ")}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="rounded-lg border bg-card p-4">
        {bars.length ? (
          <PriceChart
            bars={bars}
            overlays={overlaySeries}
            macd={showMacd ? (indicatorBundle?.macd ?? null) : null}
          />
        ) : (
          <p className="py-12 text-center text-sm text-muted-foreground">
            No bars in this timeframe.
          </p>
        )}
      </div>

      {indicators.includes("rsi_14") && indicatorBundle?.series.rsi_14 ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Latest RSI(14):{" "}
          <span className="font-mono text-foreground">
            {indicatorBundle.series.rsi_14[indicatorBundle.series.rsi_14.length - 1]?.value.toFixed(
              2,
            ) ?? "—"}
          </span>
        </p>
      ) : null}

      <section className="mt-12">
        <h2 className="mb-4 text-lg font-semibold">Recent news</h2>
        <NewsList articles={news} />
      </section>
    </div>
  );
}
