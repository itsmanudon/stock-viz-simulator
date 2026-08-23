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
import { OptionsPositions } from "@/components/options-positions";
import { PortfolioAnalyticsSection } from "@/components/portfolio-analytics";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { listOptionsPositions } from "@/lib/api/options";
import {
  getDividends,
  getPortfolio,
  getPortfolioAnalytics,
  getPortfolioHistory,
} from "@/lib/api/trading";

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

function fmtCurrency(raw: string | null, ccy = "USD"): string {
  if (raw === null) return "—";
  const n = Number(raw);
  // JPY has no minor unit; force 0 fraction digits so totals look right.
  const opts: Intl.NumberFormatOptions = {
    style: "currency",
    currency: ccy,
    minimumFractionDigits: ccy === "JPY" ? 0 : 2,
    maximumFractionDigits: ccy === "JPY" ? 0 : 2,
  };
  try {
    return n.toLocaleString("en-US", opts);
  } catch {
    // Bad ccy code — fall back to a bare number rather than throwing.
    return `${ccy} ${n.toFixed(2)}`;
  }
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

  const emptyDividends = { ytd_income: "0", history: [], projected: [] };
  const [portfolio, history, dividends, analytics, optionsPositions] = await Promise.all([
    getPortfolio(),
    getPortfolioHistory(days).catch(() => [] as Awaited<ReturnType<typeof getPortfolioHistory>>),
    getDividends().catch(() => emptyDividends),
    getPortfolioAnalytics().catch(
      () => null as Awaited<ReturnType<typeof getPortfolioAnalytics>> | null,
    ),
    listOptionsPositions().catch(() => [] as Awaited<ReturnType<typeof listOptionsPositions>>),
  ]);

  const displayCcy = portfolio.display_currency || "USD";
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
            <p className="text-xs text-muted-foreground">Total value ({displayCcy})</p>
            <p className="mt-1 font-mono text-xl">
              {fmtCurrency(portfolio.total_value, displayCcy)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Cash</p>
            <p className="mt-1 font-mono text-xl">
              {fmtCurrency(portfolio.cash_balance, displayCcy)}
            </p>
            {Number(portfolio.reserved_cash) > 0 ? (
              <p className="mt-0.5 text-xs text-muted-foreground">
                Reserved {fmtCurrency(portfolio.reserved_cash, displayCcy)} · Available{" "}
                {fmtCurrency(portfolio.available_cash, displayCcy)}
              </p>
            ) : (
              <p className="mt-0.5 text-xs text-muted-foreground">
                Available {fmtCurrency(portfolio.available_cash, displayCcy)}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Market value</p>
            <p className="mt-1 font-mono text-xl">
              {fmtCurrency(portfolio.market_value, displayCcy)}
            </p>
            {Number(portfolio.options_market_value) !== 0 ? (
              <p className="mt-0.5 text-xs text-muted-foreground">
                + {fmtCurrency(portfolio.options_market_value, displayCcy)} options
              </p>
            ) : null}
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
              {fmtCurrency(portfolio.unrealized_pl, displayCcy)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">{fmtPct(unrealized, totalCost)}</p>
          </CardContent>
        </Card>
      </div>

      {analytics ? <PortfolioAnalyticsSection analytics={analytics} /> : null}

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
        <h2 className="mb-3 text-lg font-semibold">Dividend income</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">YTD income</p>
              <p className="mt-1 font-mono text-xl text-green-500">
                {fmtCurrency(dividends.ytd_income, "USD")}
              </p>
            </CardContent>
          </Card>
          {dividends.projected.length > 0 && (
            <Card>
              <CardContent className="p-4">
                <p className="mb-2 text-xs text-muted-foreground">Upcoming payouts</p>
                <ul className="space-y-1 text-sm">
                  {dividends.projected.slice(0, 3).map((p) => (
                    <li key={p.ticker} className="flex justify-between gap-4">
                      <span className="font-mono font-semibold">{p.ticker}</span>
                      <span className="text-muted-foreground">
                        {p.projected_ex_date ?? "unknown date"}
                      </span>
                      <span className="font-mono text-green-500">
                        +{fmtCurrency(p.projected_amount, "USD")}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
        {dividends.history.length > 0 && (
          <div className="mt-3 rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Ex-date</TableHead>
                  <TableHead className="text-right">Amount credited</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dividends.history.map((d) => (
                  <TableRow key={`${d.ticker}-${d.ex_date}`}>
                    <TableCell className="font-mono font-semibold">{d.ticker}</TableCell>
                    <TableCell className="text-muted-foreground">{d.ex_date}</TableCell>
                    <TableCell className="text-right font-mono text-green-500">
                      +{fmtCurrency(d.amount_credited, "USD")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {dividends.history.length === 0 && (
          <p className="mt-2 text-sm text-muted-foreground">
            No dividends credited yet. Dividends are applied on ex-dates for held positions.
          </p>
        )}
      </section>

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
                  <TableHead className="hidden text-right sm:table-cell">Ccy</TableHead>
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
                  const nativeCcy = p.currency || "USD";
                  const showNativeHint = nativeCcy !== displayCcy;
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
                      <TableCell className="hidden text-right font-mono text-xs text-muted-foreground sm:table-cell">
                        {nativeCcy}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {fmtQty(p.quantity)}
                        {Number(p.reserved_quantity) > 0 ? (
                          <span className="ml-1 block text-xs text-muted-foreground">
                            {fmtQty(p.available_quantity)} avail
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="hidden text-right font-mono md:table-cell">
                        {fmtCurrency(p.avg_cost, nativeCcy)}
                      </TableCell>
                      <TableCell className="hidden text-right font-mono sm:table-cell">
                        {fmtCurrency(p.last_close, nativeCcy)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {fmtCurrency(p.market_value, displayCcy)}
                        {showNativeHint ? (
                          <span className="ml-1 block text-xs text-muted-foreground">
                            {fmtCurrency(p.market_value_native, nativeCcy)}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono ${
                          pl > 0 ? "text-green-500" : pl < 0 ? "text-red-500" : ""
                        }`}
                      >
                        {fmtCurrency(p.unrealized_pl, displayCcy)}
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

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">Options positions</h2>
        <OptionsPositions positions={optionsPositions} />
      </section>
    </div>
  );
}
