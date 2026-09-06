"use client";

import type { JournalMonth } from "@/lib/api/journal";
import { formatMonthLabel, winRatePercent } from "@/lib/journal-view-model";
import { formatSignedPercent } from "@/lib/portfolio-view-model";
import { cn } from "@/lib/utils";

/**
 * The month's headline figures above the calendar.
 *
 * Four numbers, no more. Metrics that cannot be derived honestly are hidden
 * rather than filled in: the percentage disappears without a NAV snapshot to
 * measure against, and the win rate disappears when no trade was decided.
 */
export function JournalSummary({
  monthKey,
  data,
  loading,
}: {
  monthKey: string;
  data: JournalMonth | null;
  loading: boolean;
}) {
  if (!data) {
    return (
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-y border-border-muted py-4 sm:grid-cols-4">
        {["Realized P&L", "% of prior NAV", "Trades", "Win rate"].map((label) => (
          <Metric key={label} label={label} value={null} loading={loading} />
        ))}
      </dl>
    );
  }

  const pnl = Number(data.summary.realized_pnl);
  const winRate = winRatePercent(data.summary);

  return (
    <>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-y border-border-muted py-4 sm:grid-cols-4">
        <Metric
          label={`Realized P&L · ${data.currency}`}
          value={
            <span className={pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : undefined}>
              {pnl > 0 ? "+" : pnl < 0 ? "−" : ""}
              {Math.abs(pnl).toLocaleString("en-US", {
                style: "currency",
                currency: data.currency,
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
          }
          loading={loading}
        />
        <Metric
          label="% of prior NAV"
          value={
            data.return_pct === null ? null : (
              <span
                className={
                  data.return_pct > 0
                    ? "text-positive"
                    : data.return_pct < 0
                      ? "text-negative"
                      : undefined
                }
              >
                {formatSignedPercent(data.return_pct)}
              </span>
            )
          }
          loading={loading}
        />
        <Metric
          label="Trades"
          value={data.summary.trade_count.toLocaleString("en-US")}
          loading={loading}
        />
        <Metric
          label="Win rate"
          value={winRate === null ? null : `${winRate.toFixed(0)}%`}
          loading={loading}
        />
      </dl>

      <p className="mt-2 text-xs text-muted-foreground">
        Realized P&L only, in {data.currency}, from closed positions in {formatMonthLabel(monthKey)}
        . Open positions, dividends, and cash movements are excluded.
        {data.return_pct === null
          ? " The percentage needs a portfolio snapshot from before the month, so it is not shown."
          : ` Measured against the last recorded ${Number(data.start_nav).toLocaleString("en-US", {
              style: "currency",
              currency: data.currency,
              maximumFractionDigits: 0,
            })} of net asset value before the month. This is not portfolio return.`}
      </p>
    </>
  );
}

function Metric({
  label,
  value,
  loading,
}: {
  label: string;
  value: React.ReactNode;
  loading: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-xs font-medium text-muted-foreground">{label}</dt>
      <dd
        data-financial
        className={cn(
          "mt-1 font-mono text-xl font-semibold tracking-tight sm:text-2xl",
          value === null && "text-text-tertiary",
        )}
      >
        {/* A fixed-width placeholder rather than a spinner: the row must not
            change height between loading and loaded. */}
        {loading && value === null ? (
          <span className="inline-block h-6 w-24 animate-pulse rounded-sm bg-surface-secondary align-middle" />
        ) : (
          (value ?? "—")
        )}
      </dd>
    </div>
  );
}
