/**
 * /portfolio — cash + holdings + P&L snapshot.
 *
 * Pulls /v1/portfolio (auto-creates the default $100k portfolio on first
 * read). Renders the aggregates as a header strip and the positions as a
 * shadcn Table; clicking a row deep-links to /stocks/[ticker]. When at least
 * two NAV snapshots exist for the user, an equity-curve area chart appears
 * above the positions with a 30 / 90 / All range toggle.
 */

import Link from "next/link";

import { EquityCurve } from "@/components/equity-curve";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getPortfolio, getPortfolioHistory } from "@/lib/api/trading";

const RANGES = [
  { value: "30", label: "30D", days: 30 },
  { value: "90", label: "90D", days: 90 },
  { value: "all", label: "All", days: null as number | null },
] as const;

type RangeValue = (typeof RANGES)[number]["value"];

function parseRange(raw: string | undefined): RangeValue {
  const valid = RANGES.find((r) => r.value === raw)?.value;
  return valid ?? "90";
}

function fmtCurrency(raw: string | null): string {
  if (raw === null) return "—";
  const n = Number(raw);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtPct(numerator: number, denominator: number): string {
  if (denominator === 0) return "—";
  const pct = (numerator / denominator) * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function fmtQty(raw: string): string {
  const n = Number(raw);
  return n.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export default async function PortfolioPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const { range: rawRange } = await searchParams;
  const range = parseRange(rawRange);
  const days = RANGES.find((r) => r.value === range)?.days ?? 90;

  const [portfolio, history] = await Promise.all([getPortfolio(), getPortfolioHistory(days)]);

  const totalCost = Number(portfolio.total_cost_basis);
  const unrealized = Number(portfolio.unrealized_pl);

  const totalReturnPct = (() => {
    if (history.length < 2) return null;
    const first = Number(history[0].nav);
    const last = Number(history[history.length - 1].nav);
    if (first === 0) return null;
    return ((last - first) / first) * 100;
  })();

  const hasChart = history.length >= 2;

  return (
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Portfolio</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Paper trading. Positions priced at the latest EOD close.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Total value</p>
            <p className="mt-1 font-mono text-xl">{fmtCurrency(portfolio.total_value)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Cash</p>
            <p className="mt-1 font-mono text-xl">{fmtCurrency(portfolio.cash_balance)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Market value</p>
            <p className="mt-1 font-mono text-xl">{fmtCurrency(portfolio.market_value)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Unrealized P&amp;L</p>
            <p
              className={`mt-1 font-mono text-xl ${
                unrealized > 0 ? "text-green-500" : unrealized < 0 ? "text-red-500" : ""
              }`}
            >
              {fmtCurrency(portfolio.unrealized_pl)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">{fmtPct(unrealized, totalCost)}</p>
          </CardContent>
        </Card>
      </div>

      {hasChart ? (
        <section className="mt-8">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <div className="flex items-baseline gap-3">
              <h2 className="text-lg font-semibold">Performance</h2>
              {totalReturnPct !== null ? (
                <span
                  className={`font-mono text-sm ${
                    totalReturnPct >= 0 ? "text-green-500" : "text-red-500"
                  }`}
                >
                  {totalReturnPct >= 0 ? "+" : ""}
                  {totalReturnPct.toFixed(2)}%
                </span>
              ) : null}
            </div>
            <nav className="flex gap-1">
              {RANGES.map((r) => (
                <Link
                  key={r.value}
                  href={`/portfolio?range=${r.value}`}
                  className={`rounded-md border px-2.5 py-1 text-xs transition hover:bg-accent ${
                    range === r.value ? "border-primary text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {r.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <EquityCurve points={history} />
          </div>
        </section>
      ) : null}

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">Positions</h2>
        {portfolio.positions.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No open positions yet.{" "}
              <Link href="/trade" className="text-foreground underline">
                Place your first trade →
              </Link>
            </CardContent>
          </Card>
        ) : (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[120px]">Ticker</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Avg cost</TableHead>
                  <TableHead className="text-right">Last close</TableHead>
                  <TableHead className="text-right">Market value</TableHead>
                  <TableHead className="text-right">Unrealized P&amp;L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {portfolio.positions.map((p) => {
                  const pl = Number(p.unrealized_pl);
                  const cost = Number(p.avg_cost) * Number(p.quantity);
                  return (
                    <TableRow key={p.ticker}>
                      <TableCell className="font-mono font-semibold">
                        <Link href={`/stocks/${p.ticker}`} className="hover:underline">
                          {p.ticker}
                        </Link>
                      </TableCell>
                      <TableCell className="truncate text-muted-foreground">{p.name}</TableCell>
                      <TableCell className="text-right font-mono">{fmtQty(p.quantity)}</TableCell>
                      <TableCell className="text-right font-mono">
                        {fmtCurrency(p.avg_cost)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {fmtCurrency(p.last_close)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {fmtCurrency(p.market_value)}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono ${
                          pl > 0 ? "text-green-500" : pl < 0 ? "text-red-500" : ""
                        }`}
                      >
                        {fmtCurrency(p.unrealized_pl)}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {fmtPct(pl, cost)}
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
