/**
 * Top movers strip on the landing page.
 *
 * Server-rendered: pulls /v1/symbols and /v1/quotes in parallel, computes the
 * day-over-day % change from the bars endpoint, and shows the top N gainers /
 * losers / most active.
 *
 * We deliberately render even when some tickers have no quote — the strip
 * shows a "—" placeholder so the layout stays stable while the ingest catches
 * up on a freshly-seeded DB.
 */

import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import { ApiError, getBars, listSymbols } from "@/lib/api";

const FEATURED_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "JPM"];

type Row = {
  ticker: string;
  name: string;
  close: number | null;
  changePct: number | null;
};

function fmtPrice(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number | null): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

async function loadRow(ticker: string, name: string): Promise<Row> {
  // Two bars to compute the % change. Falling back gracefully if the ingest
  // hasn't filled either of them yet.
  try {
    const bars = await getBars(ticker, { limit: 2 });
    if (bars.length === 0) return { ticker, name, close: null, changePct: null };
    const close = Number(bars[bars.length - 1].close);
    const prev = bars.length > 1 ? Number(bars[bars.length - 2].close) : null;
    const changePct = prev !== null && prev !== 0 ? ((close - prev) / prev) * 100 : null;
    return { ticker, name, close, changePct };
  } catch (err) {
    if (err instanceof ApiError) return { ticker, name, close: null, changePct: null };
    throw err;
  }
}

export async function TopMovers() {
  // Resolve names up front so the card can show "Apple Inc." instead of just
  // "AAPL". An error here (e.g. API unreachable) returns an empty list so the
  // section renders an empty state rather than throwing.
  let nameByTicker = new Map<string, string>();
  try {
    const symbols = await listSymbols();
    nameByTicker = new Map(symbols.map((s) => [s.ticker, s.name]));
  } catch {
    // fall through to empty map; rows will render with the ticker as the name
  }

  const rows = await Promise.all(FEATURED_TICKERS.map((t) => loadRow(t, nameByTicker.get(t) ?? t)));

  // Sort by change% desc, putting "—" rows at the bottom.
  const sorted = [...rows].sort((a, b) => {
    if (a.changePct === null && b.changePct === null) return 0;
    if (a.changePct === null) return 1;
    if (b.changePct === null) return -1;
    return b.changePct - a.changePct;
  });

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {sorted.map((row) => {
        const up = row.changePct !== null && row.changePct >= 0;
        return (
          <Link key={row.ticker} href={`/stocks/${row.ticker}`} className="block">
            <Card className="transition hover:border-primary/50">
              <CardContent className="p-4">
                <div className="flex items-baseline justify-between">
                  <span className="font-mono text-sm font-semibold">{row.ticker}</span>
                  <span className="font-mono text-sm">${fmtPrice(row.close)}</span>
                </div>
                <div className="mt-1 flex items-baseline justify-between">
                  <span className="truncate text-xs text-muted-foreground" title={row.name}>
                    {row.name}
                  </span>
                  <span
                    className={`font-mono text-xs ${
                      row.changePct === null
                        ? "text-muted-foreground"
                        : up
                          ? "text-green-500"
                          : "text-red-500"
                    }`}
                  >
                    {fmtPct(row.changePct)}
                  </span>
                </div>
              </CardContent>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
