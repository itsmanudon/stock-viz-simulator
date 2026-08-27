import Link from "next/link";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DividendSummary, Position } from "@/lib/api/trading";
import {
  currencyForProjectedDividend,
  formatCurrency,
  formatSignedCurrency,
} from "@/lib/portfolio-view-model";

export function PortfolioIncome({
  dividends,
  positions,
}: {
  dividends: DividendSummary | null;
  positions: Position[];
}) {
  if (dividends === null) {
    return (
      <p className="border-y border-border-muted py-8 text-sm text-muted-foreground">
        Income data is temporarily unavailable.
      </p>
    );
  }

  const hasIncome =
    Number(dividends.ytd_income) !== 0 ||
    dividends.projected.length > 0 ||
    dividends.history.length > 0;

  if (!hasIncome) {
    return (
      <div className="border-y border-border-muted py-8 text-sm">
        <p className="font-medium">No dividend income has been credited yet.</p>
        <p className="mt-1 text-muted-foreground">
          Credited and upcoming distributions for held securities will appear here.
        </p>
      </div>
    );
  }

  return (
    <section aria-labelledby="portfolio-income-heading" className="space-y-8">
      <div>
        <h2 id="portfolio-income-heading" className="text-lg font-semibold tracking-tight">
          Portfolio income
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Credited income is recorded in USD; projections retain each security's native currency.
        </p>
        <div className="mt-5 border-y border-border-muted py-4">
          <p className="text-xs font-medium text-muted-foreground">YTD credited income · USD</p>
          <p className="mt-1 font-mono text-2xl font-semibold text-positive" data-financial>
            {formatCurrency(dividends.ytd_income, "USD")}
          </p>
        </div>
      </div>

      {dividends.projected.length > 0 ? (
        <section aria-labelledby="upcoming-income-heading">
          <h3 id="upcoming-income-heading" className="text-sm font-semibold">
            Upcoming
          </h3>
          <ul className="mt-3 divide-y divide-border-muted border-y border-border-muted">
            {dividends.projected.map((projection, index) => {
              const currency = currencyForProjectedDividend(projection.ticker, positions);
              return (
                <li
                  key={`${projection.ticker}-${projection.projected_ex_date ?? "unknown"}-${index}`}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3"
                >
                  <div>
                    <Link
                      href={`/stocks/${projection.ticker}`}
                      className="font-mono text-sm font-semibold hover:text-brand"
                    >
                      {projection.ticker}
                    </Link>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {projection.projected_ex_date
                        ? `Expected ex-date ${formatDate(projection.projected_ex_date)}`
                        : "Expected ex-date unavailable"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-sm font-medium" data-financial>
                      {currency
                        ? formatCurrency(projection.projected_amount, currency)
                        : `${formatBareAmount(projection.projected_amount)} · Currency unavailable`}
                    </p>
                    {currency ? (
                      <p className="mt-0.5 text-[11px] text-muted-foreground">Native projection</p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {dividends.history.length > 0 ? (
        <section aria-labelledby="income-history-heading">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 id="income-history-heading" className="text-sm font-semibold">
              History
            </h3>
            <p className="text-xs text-muted-foreground">Credited in USD</p>
          </div>
          <div className="overflow-hidden border-y border-border-muted">
            <Table aria-label="Dividend income history">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Symbol</TableHead>
                  <TableHead>Ex-date</TableHead>
                  <TableHead className="text-right">Amount credited · USD</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dividends.history.map((credit) => (
                  <TableRow
                    key={`${credit.ticker}-${credit.ex_date}`}
                    className="border-border-muted"
                  >
                    <TableCell>
                      <Link
                        href={`/stocks/${credit.ticker}`}
                        className="font-mono font-semibold hover:text-brand"
                      >
                        {credit.ticker}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(credit.ex_date)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-positive" data-financial>
                      {formatSignedCurrency(credit.amount_credited, "USD")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>
      ) : null}
    </section>
  );
}

function formatDate(raw: string): string {
  return new Date(`${raw}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatBareAmount(raw: string): string {
  const value = Number(raw);
  return Number.isFinite(value)
    ? value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";
}
