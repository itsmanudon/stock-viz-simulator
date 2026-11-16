import type { PeriodReturn, PortfolioReturns, Xirr } from "@/lib/api/trading";
import { formatSignedPercent } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";

const PERIOD_LABELS: Record<string, string> = {
  "1M": "1 month",
  "3M": "3 months",
  YTD: "Year to date",
  "1Y": "1 year",
  ALL: "Since start",
};

/**
 * Phase 8.1: the account's time-weighted return by period and each holding's
 * money-weighted (XIRR) return. Every figure names its method and basis
 * beside it (UX-9); a missing figure says why instead of showing 0.
 */
export function PortfolioReturnsPanel({ returns }: { returns: PortfolioReturns | null }) {
  if (!returns) {
    return (
      <p className="py-6 text-sm text-muted-foreground">
        Returns are unavailable right now. Try again shortly.
      </p>
    );
  }
  return (
    <div className="grid gap-6 py-5 lg:grid-cols-2">
      <section aria-labelledby="twr-heading">
        <h3 id="twr-heading" className="text-sm font-semibold">
          Time-weighted return
        </h3>
        <p className="mt-1 text-2xs text-text-tertiary">
          Method: time-weighted, {returns.twr_basis}. In {returns.currency}. Annualised only past
          one year.
        </p>
        <table aria-label="Time-weighted return by period" className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-2xs text-text-tertiary">
              <th className="py-1.5 font-medium">Period</th>
              <th className="py-1.5 font-medium">From</th>
              <th className="py-1.5 text-right font-medium">Return</th>
              <th className="py-1.5 text-right font-medium">Per year</th>
            </tr>
          </thead>
          <tbody>
            {returns.periods.map((row) => (
              <PeriodRow key={row.period} row={row} />
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="xirr-heading">
        <h3 id="xirr-heading" className="text-sm font-semibold">
          Money-weighted return (XIRR)
        </h3>
        <p className="mt-1 text-2xs text-text-tertiary">
          Method: XIRR of {returns.xirr_basis}. Annual rate; needs 30 days of history.
        </p>
        <table aria-label="Money-weighted return by holding" className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-2xs text-text-tertiary">
              <th className="py-1.5 font-medium">Holding</th>
              <th className="py-1.5 font-medium">Since</th>
              <th className="py-1.5 text-right font-medium">Per year</th>
            </tr>
          </thead>
          <tbody>
            <XirrRow label="Whole account" result={returns.account_xirr} />
            {returns.holdings.map((h) => (
              <XirrRow
                key={`${h.kind}-${h.ticker}`}
                label={h.kind === "options" ? "Options book" : h.ticker}
                ticker={h.kind === "options" ? undefined : h.ticker}
                result={h.xirr}
              />
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function PeriodRow({ row }: { row: PeriodReturn }) {
  return (
    <tr className="border-t border-border-muted">
      <td className="py-2">{PERIOD_LABELS[row.period] ?? row.period}</td>
      <td className="py-2 text-xs text-text-secondary">
        {row.start_date ? formatCloseDate(row.start_date) : "—"}
      </td>
      <td className="py-2 text-right font-mono" data-financial>
        {row.return_pct === null ? (
          <span className="font-sans text-xs text-text-tertiary">{row.reason ?? "—"}</span>
        ) : (
          formatSignedPercent(row.return_pct)
        )}
      </td>
      <td className="py-2 text-right font-mono" data-financial>
        {row.annualised_pct === null ? "—" : formatSignedPercent(row.annualised_pct)}
      </td>
    </tr>
  );
}

function XirrRow({ label, ticker, result }: { label: string; ticker?: string; result: Xirr }) {
  return (
    <tr className="border-t border-border-muted">
      <td className={ticker ? "ticker py-2 font-semibold" : "py-2"}>{label}</td>
      <td className="py-2 text-xs text-text-secondary">
        {result.first_flow ? formatCloseDate(result.first_flow) : "—"}
      </td>
      <td className="py-2 text-right font-mono" data-financial>
        {result.rate_pct === null ? (
          <span className="font-sans text-xs text-text-tertiary">{result.reason ?? "—"}</span>
        ) : (
          formatSignedPercent(result.rate_pct)
        )}
      </td>
    </tr>
  );
}
