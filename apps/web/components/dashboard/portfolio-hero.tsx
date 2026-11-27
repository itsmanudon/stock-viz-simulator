import { BookLink as Link } from "@/components/book-link";
import { ArrowLeftRight, ArrowUpRight, Bell, FlaskConical, ListOrdered } from "lucide-react";

import { DeltaPill } from "@/components/dashboard/delta-pill";
import { NavSparkline } from "@/components/dashboard/nav-sparkline";
import { PaperCard } from "@/components/paper-card";
import { RollingFigure } from "@/components/prism/rolling-figure";
import { TiltCard } from "@/components/prism/tilt-card";
import { ValuationNotice } from "@/components/valuation-notice";
import type { Portfolio, PortfolioHistoryPoint } from "@/lib/api/trading";
import { formatDateLabel } from "@/lib/journal-view-model";
import {
  DASHBOARD_HISTORY_DAYS,
  calculateNavChange,
  formatCurrency,
  formatSignedCurrency,
  formatSignedPercent,
  splitMinorUnits,
} from "@/lib/portfolio-view-model";

const COMPOSITION_SHADES = [
  "var(--brand-gradient-via)",
  "var(--brand-gradient-from)",
  "var(--brand-gradient-to)",
  "var(--text-tertiary)",
] as const;

const ACTIONS = [
  { label: "Trade", href: "/trade", icon: ArrowLeftRight },
  { label: "Orders", href: "/orders", icon: ListOrdered },
  { label: "Backtest", href: "/backtest", icon: FlaskConical },
  { label: "Alerts", href: "/alerts", icon: Bell },
] as const;

/**
 * The dashboard's headline widget, in the Aurora direction: the paper account
 * card over a soft brand glow, the account value with dimmed minor units
 * (Revolut's balance treatment), four round actions, then the NAV curve and
 * the value breakdown.
 *
 * The glow and card are the only brand colour in the signed-in product; the
 * change line and curve keep the semantic gain/loss tokens. The value is
 * labelled as simulated and dated by the latest snapshot it comes from.
 */
export function PortfolioHero({
  portfolio,
  history,
  book = null,
}: {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  /** A5.2: the selected book, or All books with how many it sums. */
  book?: { name: string; kind: "paper" | "imported" | "all"; count: number } | null;
}) {
  const isAll = book?.kind === "all";
  const currency = portfolio.display_currency || "USD";
  const change = history ? calculateNavChange(history) : null;
  // The latest session's move: the last two snapshots (Aurora board v3 shows
  // it beside the period change). With only two snapshots it would repeat the
  // period change, so it needs at least three.
  const dayChange = history && history.length >= 3 ? calculateNavChange(history.slice(-2)) : null;
  const values = history?.map((point) => Number(point.nav)).filter(Number.isFinite) ?? [];
  const rising = change === null || change.absolute >= 0;
  const lastSnapshot = history && history.length > 0 ? history[history.length - 1].date : null;
  const [major, minor] = splitMinorUnits(formatCurrency(portfolio.total_value, currency));

  const breakdown = [
    { label: "Equities", value: portfolio.market_value },
    { label: "Options", value: portfolio.options_market_value },
    { label: "Available cash", value: portfolio.available_cash },
    { label: "Reserved by orders", value: portfolio.reserved_cash },
  ].filter((entry) => Number(entry.value) !== 0);

  // Inside redesign (27 Nov 2026): what the value is made of, as one bar, in
  // the metal's neutral shades (a share of the account is not a gain or a
  // loss). Only parts that are positive and finite are drawn; the figures
  // beside it are the same ones the strip below prints.
  const total = Number(portfolio.total_value);
  const composition =
    Number.isFinite(total) && total > 0
      ? breakdown
          .map((entry, index) => ({
            ...entry,
            share: Number(entry.value) / total,
            shade: COMPOSITION_SHADES[index % COMPOSITION_SHADES.length],
          }))
          .filter((entry) => Number.isFinite(entry.share) && entry.share > 0)
      : [];
  const unrealized = Number(portfolio.unrealized_pl);
  const positionsCount = portfolio.positions.length + portfolio.option_positions.length;

  return (
    <section
      aria-labelledby="dashboard-hero-heading"
      className="@container relative isolate flex h-full min-w-0 flex-col overflow-hidden rounded-xl border border-border-muted bg-card"
    >
      <div
        aria-hidden
        className="brand-glow -top-24 -left-20 -z-10 h-80 w-[28rem] max-w-[120%] opacity-80"
      />

      <div className="grid gap-5 p-4 sm:p-5 @xl:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] @xl:items-center @xl:gap-8">
        <TiltCard className="w-full max-w-72 justify-self-center @xl:justify-self-start">
          <PaperCard
            accountId={isAll ? undefined : portfolio.portfolio_id}
            currency={currency}
            badge={isAll ? "All Books" : book?.kind === "imported" ? "Imported" : "Paper"}
            title={isAll ? `${book?.count ?? 0} Books · ${currency}` : undefined}
            className="w-full"
          />
        </TiltCard>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2
                id="dashboard-hero-heading"
                className="flex flex-wrap items-center gap-2 text-sm font-medium text-text-secondary"
              >
                Portfolio value
                {book ? (
                  <span className="rounded-full border border-brand/40 px-2 py-0.5 text-2xs font-medium text-foreground">
                    {isAll ? `All books · ${book.count}` : book.name}
                  </span>
                ) : null}
                <span className="rounded-full border border-border-muted px-2 py-0.5 text-2xs font-medium text-text-tertiary">
                  Simulated
                </span>
              </h2>
              <p
                className="mt-2 break-all font-mono text-3xl font-medium tracking-tight sm:text-4xl"
                data-financial
              >
                <RollingFigure text={major} />
                {minor ? <RollingFigure text={minor} className="figure-minor" /> : null}
              </p>
            </div>
            <Link
              href="/portfolio"
              className="group inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-text-secondary transition-colors hover:text-brand"
            >
              Open portfolio
              <ArrowUpRight className="size-3.5 transition-transform group-hover:-translate-y-px" />
            </Link>
          </div>

          <ValuationNotice warnings={portfolio.valuation_warnings} />

          {change ? (
            <div className="flex flex-wrap items-center gap-2">
              <DeltaPill value={formatSignedPercent(change.percent)} />
              <span className="font-mono text-sm text-text-secondary" data-financial>
                {formatSignedCurrency(change.absolute, currency)}
              </span>
              <span className="text-xs text-text-tertiary">last {DASHBOARD_HISTORY_DAYS} days</span>
              {dayChange ? (
                <>
                  <span aria-hidden className="text-text-tertiary">
                    ·
                  </span>
                  <DeltaPill value={formatSignedPercent(dayChange.percent)} />
                  <span className="font-mono text-sm text-text-secondary" data-financial>
                    {formatSignedCurrency(dayChange.absolute, currency)}
                  </span>
                  <span className="text-xs text-text-tertiary">last session</span>
                </>
              ) : null}
            </div>
          ) : (
            <p className="text-xs text-text-tertiary">
              Change appears once you have two days of history.
            </p>
          )}

          {lastSnapshot ? (
            <p className="text-2xs text-text-tertiary">
              Valued at stored end-of-day closes · snapshot of{" "}
              {formatDateLabel(lastSnapshot, { short: true })}
            </p>
          ) : null}

          <nav aria-label="Portfolio actions" className="grid grid-cols-4 gap-2 sm:max-w-sm">
            {ACTIONS.map((action) => {
              const Icon = action.icon;
              return (
                <Link
                  key={action.href}
                  href={action.href}
                  className="group flex min-w-0 flex-col items-center gap-1.5 rounded-lg py-1 text-2xs font-medium text-text-secondary transition-colors hover:text-foreground"
                >
                  <span className="grid size-11 place-items-center rounded-full border border-border-muted bg-surface-secondary transition-colors group-hover:bg-surface-hover">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  {action.label}
                </Link>
              );
            })}
          </nav>
        </div>
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

      {composition.length > 0 ? (
        <div
          className="border-t border-border-muted px-4 pt-3 sm:px-5"
          data-testid="hero-composition"
        >
          <p className="sr-only">
            The value is made of{" "}
            {composition
              .map((entry) => `${entry.label.toLowerCase()} ${(entry.share * 100).toFixed(0)}%`)
              .join(", ")}
            .
          </p>
          <div aria-hidden className="flex h-1.5 w-full gap-0.5 overflow-hidden rounded-full">
            {composition.map((entry) => (
              <span
                key={entry.label}
                className="hero-composition-part h-full rounded-full"
                style={{ width: `${entry.share * 100}%`, background: entry.shade }}
              />
            ))}
          </div>
        </div>
      ) : null}

      {breakdown.length > 0 ? (
        <dl className="mt-auto grid grid-cols-2 bg-card sm:auto-cols-fr sm:grid-flow-col sm:grid-cols-none">
          {breakdown.map((entry) => {
            const part = composition.find((c) => c.label === entry.label);
            return (
              <div
                key={entry.label}
                className="min-w-0 border-border-muted px-4 py-3 sm:border-l sm:first:border-l-0 sm:px-5"
              >
                <dt className="flex items-center gap-1.5 text-2xs font-medium text-text-tertiary">
                  {part ? (
                    <span
                      aria-hidden
                      className="size-1.5 shrink-0 rounded-full"
                      style={{ background: part.shade }}
                    />
                  ) : null}
                  {entry.label}
                  {part ? (
                    <span className="font-mono text-text-tertiary/80">
                      {(part.share * 100).toFixed(0)}%
                    </span>
                  ) : null}
                </dt>
                <dd className="mt-0.5 break-all font-mono text-sm font-semibold" data-financial>
                  {formatCurrency(entry.value, currency)}
                </dd>
              </div>
            );
          })}
          {Number.isFinite(unrealized) ? (
            <div className="min-w-0 border-border-muted px-4 py-3 sm:border-l sm:px-5">
              <dt className="text-2xs font-medium text-text-tertiary">Unrealized P&amp;L</dt>
              <dd
                className={`mt-0.5 break-all font-mono text-sm font-semibold ${
                  unrealized > 0 ? "text-positive" : unrealized < 0 ? "text-negative" : ""
                }`}
                data-financial
              >
                {unrealized > 0 ? "▲ " : unrealized < 0 ? "▼ " : ""}
                {formatSignedCurrency(unrealized, currency)}
              </dd>
            </div>
          ) : null}
          <div className="min-w-0 border-border-muted px-4 py-3 sm:border-l sm:px-5">
            <dt className="text-2xs font-medium text-text-tertiary">Open positions</dt>
            <dd className="mt-0.5 font-mono text-sm font-semibold">{positionsCount}</dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}
