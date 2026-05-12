/**
 * /portfolio — cash + holdings + P&L snapshot.
 *
 * Pulls /v1/portfolio (auto-creates the default $100k portfolio on first
 * read). Renders the aggregates as a header strip and the positions as a
 * shadcn Table; clicking a row deep-links to /stocks/[ticker].
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
import { getPortfolio } from "@/lib/api/trading";

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

export default async function PortfolioPage() {
  const portfolio = await getPortfolio();
  const totalCost = Number(portfolio.total_cost_basis);
  const unrealized = Number(portfolio.unrealized_pl);

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
                  <TableHead className="w-[100px] md:w-[120px]">Ticker</TableHead>
                  <TableHead className="hidden md:table-cell">Name</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="hidden text-right md:table-cell">Avg cost</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Last close</TableHead>
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
                      <TableCell className="hidden truncate text-muted-foreground md:table-cell">
                        {p.name}
                      </TableCell>
                      <TableCell className="text-right font-mono">{fmtQty(p.quantity)}</TableCell>
                      <TableCell className="hidden text-right font-mono md:table-cell">
                        {fmtCurrency(p.avg_cost)}
                      </TableCell>
                      <TableCell className="hidden text-right font-mono sm:table-cell">
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
