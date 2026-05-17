/**
 * Analytics block rendered on /portfolio.
 *
 * Pure presentational — the server component fetches the analytics payload
 * and hands it down. We render: four stat cards, a sector allocation bar
 * list (no chart lib — just proportional bars), and side-by-side top
 * gainers / losers tables.
 */

import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PortfolioAnalytics } from "@/lib/api/trading";

type Props = {
  analytics: PortfolioAnalytics;
};

function fmtPct(n: number | null, digits = 2): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

function fmtSharpe(n: number | null): string {
  if (n === null) return "—";
  return n.toFixed(2);
}

function fmtCurrency(raw: string, ccy: string): string {
  const n = Number(raw);
  const opts: Intl.NumberFormatOptions = {
    style: "currency",
    currency: ccy,
    minimumFractionDigits: ccy === "JPY" ? 0 : 2,
    maximumFractionDigits: ccy === "JPY" ? 0 : 2,
  };
  try {
    return n.toLocaleString("en-US", opts);
  } catch {
    return `${ccy} ${n.toFixed(2)}`;
  }
}

function colorFor(n: number | null): string {
  if (n === null) return "";
  if (n > 0) return "text-green-500";
  if (n < 0) return "text-red-500";
  return "";
}

// Stable, accessible colors for the allocation bars. Cycles for >5 sectors.
const SECTOR_COLORS = [
  "bg-sky-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-violet-500",
  "bg-rose-500",
  "bg-teal-500",
  "bg-indigo-500",
  "bg-orange-500",
];

export function PortfolioAnalyticsSection({ analytics }: Props) {
  const {
    display_currency: ccy,
    history_days,
    total_return_pct,
    annualised_return_pct,
    sharpe_ratio,
    max_drawdown_pct,
    sector_allocation,
    top_gainers,
    top_losers,
  } = analytics;

  const hasHistory = history_days > 0;
  const hasPositions = sector_allocation.length > 0;

  return (
    <section className="mt-8">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Analytics</h2>
        {hasHistory ? (
          <p className="text-xs text-muted-foreground">
            Based on {history_days} day{history_days === 1 ? "" : "s"} of NAV history.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Time-series metrics appear once at least two daily snapshots have been recorded.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Total return</p>
            <p className={`mt-1 font-mono text-xl ${colorFor(total_return_pct)}`}>
              {fmtPct(total_return_pct)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Annualised</p>
            <p className={`mt-1 font-mono text-xl ${colorFor(annualised_return_pct)}`}>
              {fmtPct(annualised_return_pct)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Sharpe (rf 5%)</p>
            <p className="mt-1 font-mono text-xl">{fmtSharpe(sharpe_ratio)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Max drawdown</p>
            <p className={`mt-1 font-mono text-xl ${colorFor(max_drawdown_pct)}`}>
              {fmtPct(max_drawdown_pct)}
            </p>
          </CardContent>
        </Card>
      </div>

      {hasPositions && (
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card>
            <CardContent className="p-4">
              <p className="mb-3 text-sm font-medium">Sector allocation</p>
              <div className="space-y-2">
                {sector_allocation.map((slice, i) => (
                  <div key={slice.sector}>
                    <div className="mb-1 flex items-baseline justify-between text-xs">
                      <span className="text-muted-foreground">{slice.sector}</span>
                      <span className="font-mono">
                        {slice.pct.toFixed(1)}% · {fmtCurrency(slice.market_value, ccy)}
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className={`h-full ${SECTOR_COLORS[i % SECTOR_COLORS.length]}`}
                        style={{ width: `${Math.max(2, slice.pct).toFixed(2)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <p className="mb-3 text-sm font-medium">Top movers</p>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <MoversTable label="Gainers" movers={top_gainers} ccy={ccy} positive />
                <MoversTable label="Losers" movers={top_losers} ccy={ccy} positive={false} />
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </section>
  );
}

function MoversTable({
  label,
  movers,
  ccy,
  positive,
}: {
  label: string;
  movers: PortfolioAnalytics["top_gainers"];
  ccy: string;
  positive: boolean;
}) {
  return (
    <div>
      <p className="mb-2 text-xs uppercase text-muted-foreground">{label}</p>
      {movers.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {positive ? "No positions in the green." : "No positions in the red."}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-8 text-xs">Ticker</TableHead>
              <TableHead className="h-8 text-right text-xs">Return</TableHead>
              <TableHead className="h-8 text-right text-xs">P&amp;L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {movers.map((m) => (
              <TableRow key={m.ticker}>
                <TableCell className="py-1 font-mono text-sm font-semibold">
                  <Link href={`/stocks/${m.ticker}`} className="hover:underline">
                    {m.ticker}
                  </Link>
                </TableCell>
                <TableCell
                  className={`py-1 text-right font-mono text-sm ${
                    positive ? "text-green-500" : "text-red-500"
                  }`}
                >
                  {fmtPct(m.return_pct)}
                </TableCell>
                <TableCell
                  className={`py-1 text-right font-mono text-sm ${
                    positive ? "text-green-500" : "text-red-500"
                  }`}
                >
                  {fmtCurrency(m.unrealized_pl, ccy)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
