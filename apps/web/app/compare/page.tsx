/**
 * /compare?tickers=AAPL,MSFT,... — normalized line chart over a shared window.
 *
 * Pulls bars for every ticker in the query string in parallel, hands them to
 * the client-side CompareChart, and shows a per-ticker summary (return %,
 * absolute change, sector) underneath. The chart rebases each series to 100
 * at the first bar so the lines are visually comparable.
 */

import Link from "next/link";
import { redirect } from "next/navigation";

import { CompareChart } from "@/components/compare-chart";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError, type Bar, getBars, getSymbol } from "@/lib/api";

const TIMEFRAMES = [
  { value: "1M", days: 22 },
  { value: "3M", days: 65 },
  { value: "6M", days: 130 },
  { value: "1Y", days: 252 },
  { value: "5Y", days: 1260 },
] as const;

type Timeframe = (typeof TIMEFRAMES)[number]["value"];

function parseTickers(raw: string | undefined): string[] {
  if (!raw) return [];
  return Array.from(
    new Set(
      raw
        .split(",")
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ),
  ).slice(0, 6);
}

function parseTimeframe(raw: string | undefined): Timeframe {
  return TIMEFRAMES.find((t) => t.value === raw)?.value ?? "1Y";
}

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

function pct(n: number | null): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function tfHref(tickers: string[], tf: Timeframe): string {
  const params = new URLSearchParams();
  if (tickers.length) params.set("tickers", tickers.join(","));
  params.set("tf", tf);
  return `/compare?${params.toString()}`;
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ tickers?: string; tf?: string }>;
}) {
  const { tickers: rawTickers, tf: rawTf } = await searchParams;
  const tickers = parseTickers(rawTickers);
  const tf = parseTimeframe(rawTf);
  const days = TIMEFRAMES.find((t) => t.value === tf)?.days ?? 252;

  if (tickers.length === 0) {
    // Default to a sensible quartet so the page has something to show on a
    // bare visit. Redirect (rather than render in-place) so the URL reflects
    // the actual query and is shareable.
    redirect("/compare?tickers=AAPL,MSFT,GOOGL,AMZN&tf=1Y");
  }

  const seriesByTicker = await Promise.all(tickers.map((t) => loadSeries(t, days)));

  // Summary rows: total return % over the loaded window, plus sector.
  const summary = seriesByTicker.map((s) => {
    const first = s.bars[0] ? Number(s.bars[0].close) : null;
    const last = s.bars[s.bars.length - 1] ? Number(s.bars[s.bars.length - 1].close) : null;
    const returnPct =
      first !== null && last !== null && first !== 0 ? ((last - first) / first) * 100 : null;
    return { ...s, first, last, returnPct };
  });

  // Sector breakdown — count of tickers per sector in the current basket.
  const sectorCounts = summary.reduce<Map<string, number>>((acc, row) => {
    const key = row.sector ?? "Unknown";
    acc.set(key, (acc.get(key) ?? 0) + 1);
    return acc;
  }, new Map());

  return (
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Compare</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Normalized to 100 at the start of the window. Up to 6 tickers.
          </p>
        </div>
        <nav className="flex gap-1">
          {TIMEFRAMES.map((t) => (
            <Link
              key={t.value}
              href={tfHref(tickers, t.value)}
              className={`rounded-md border px-2.5 py-1 text-xs transition hover:bg-accent ${
                tf === t.value ? "border-primary text-foreground" : "text-muted-foreground"
              }`}
            >
              {t.value}
            </Link>
          ))}
        </nav>
      </header>

      <div className="rounded-lg border bg-card p-4">
        <CompareChart series={seriesByTicker.map(({ ticker, bars }) => ({ ticker, bars }))} />
      </div>

      <section className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 text-sm font-medium text-muted-foreground">Tickers</h2>
            <ul className="space-y-2 text-sm">
              {summary.map((row) => (
                <li key={row.ticker} className="flex items-baseline justify-between gap-3">
                  <Link href={`/stocks/${row.ticker}`} className="font-mono hover:underline">
                    {row.ticker}
                  </Link>
                  <span className="flex-1 truncate text-xs text-muted-foreground">{row.name}</span>
                  <span
                    className={`font-mono text-xs ${
                      row.returnPct === null
                        ? "text-muted-foreground"
                        : row.returnPct >= 0
                          ? "text-green-500"
                          : "text-red-500"
                    }`}
                  >
                    {pct(row.returnPct)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 text-sm font-medium text-muted-foreground">Sector breakdown</h2>
            <ul className="space-y-2 text-sm">
              {Array.from(sectorCounts.entries())
                .sort((a, b) => b[1] - a[1])
                .map(([sector, count]) => (
                  <li key={sector} className="flex items-baseline justify-between">
                    <span>{sector}</span>
                    <span className="font-mono text-xs text-muted-foreground">{count}</span>
                  </li>
                ))}
            </ul>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
