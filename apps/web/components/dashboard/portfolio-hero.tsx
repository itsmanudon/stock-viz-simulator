import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { DeltaPill } from "@/components/dashboard/delta-pill";
import { NavSparkline } from "@/components/dashboard/nav-sparkline";
import type { Portfolio, PortfolioHistoryPoint } from "@/lib/api/trading";
import {
  DASHBOARD_HISTORY_DAYS,
  calculateNavChange,
  formatCurrency,
  formatSignedCurrency,
  formatSignedPercent,
} from "@/lib/portfolio-view-model";

/**
 * The dashboard's headline widget: total portfolio value, its change over the
 * charted window, and the NAV curve behind it — the "big value + delta pill +
 * trend" anatomy from the Financial Dashboard reference.
 */
export function PortfolioHero({
  portfolio,
  history,
}: {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
}) {
  const currency = portfolio.display_currency || "USD";
  const change = history ? calculateNavChange(history) : null;
  const values = history?.map((point) => Number(point.nav)).filter(Number.isFinite) ?? [];
  const rising = change === null || change.absolute >= 0;

  const breakdown = [
    { label: "Equities", value: portfolio.market_value },
    { label: "Options", value: portfolio.options_market_value },
    { label: "Cash", value: portfolio.available_cash },
  ].filter((entry) => Number(entry.value) !== 0);

  return (
    <section
      aria-labelledby="dashboard-hero-heading"
      className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-border-muted bg-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5">
        <div className="min-w-0">
          <h2 id="dashboard-hero-heading" className="text-sm font-medium text-text-secondary">
            Total portfolio value
          </h2>
          <p
            className="mt-2 font-mono text-3xl font-semibold tracking-tight sm:text-4xl"
            data-financial
          >
            {formatCurrency(portfolio.total_value, currency)}
          </p>
          {change ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <DeltaPill value={formatSignedPercent(change.percent)} />
              <span className="font-mono text-sm text-text-secondary" data-financial>
                {formatSignedCurrency(change.absolute, currency)}
              </span>
              <span className="text-xs text-text-tertiary">last {DASHBOARD_HISTORY_DAYS} days</span>
            </div>
          ) : (
            <p className="mt-3 text-xs text-text-tertiary">
              Change appears once you have two days of history.
            </p>
          )}
        </div>

        <Link
          href="/portfolio"
          className="group inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-text-secondary transition-colors hover:text-brand"
        >
          Open portfolio
          <ArrowUpRight className="size-3.5 transition-transform group-hover:-translate-y-px" />
        </Link>
      </div>

      {values.length >= 2 ? (
        <div className={rising ? "text-positive" : "text-negative"}>
          <NavSparkline
            values={values}
            label={`Portfolio value over the last ${DASHBOARD_HISTORY_DAYS} days, trending ${
              rising ? "up" : "down"
            }.`}
          />
        </div>
      ) : null}

      {breakdown.length > 0 ? (
        <dl className="grid grid-cols-3 border-t border-border-muted">
          {breakdown.map((entry) => (
            <div
              key={entry.label}
              className="min-w-0 border-l border-border-muted px-4 py-3 first:border-l-0 sm:px-5"
            >
              <dt className="text-2xs font-medium text-text-tertiary">{entry.label}</dt>
              <dd className="mt-0.5 truncate font-mono text-sm font-semibold" data-financial>
                {formatCurrency(entry.value, currency)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}
