import { FigureStrip } from "@/components/figure-strip";
import type { Portfolio, PortfolioAnalytics } from "@/lib/api/trading";
import { formatCurrency, formatSignedPercent } from "@/lib/portfolio-view-model";

type Props = {
  portfolio: Portfolio;
  analytics: PortfolioAnalytics | null;
};

export function PortfolioMetrics({ portfolio, analytics }: Props) {
  const currency = portfolio.display_currency || "USD";
  const hasInvestments = portfolio.positions.length > 0 || portfolio.option_positions.length > 0;
  const metrics: Metric[] = [
    {
      label: "Available cash",
      value: formatCurrency(portfolio.available_cash, currency),
      detail:
        Number(portfolio.reserved_cash) > 0
          ? `${formatCurrency(portfolio.reserved_cash, currency)} reserved`
          : undefined,
    },
  ];

  // Cash a sale left in another currency (Phase 4.5b). The base currency's
  // cash is the "Available cash" figure above.
  const otherCash = (portfolio.cash_by_currency ?? []).slice(1).filter((c) => Number(c.amount) > 0);
  if (otherCash.length > 0) {
    const total = otherCash.reduce((sum, c) => sum + Number(c.value), 0);
    metrics.push({
      label: "Other cash",
      value: formatCurrency(total, currency),
      detail: otherCash.map((c) => formatCurrency(c.amount, c.currency)).join(" · "),
    });
  }

  if (portfolio.positions.length > 0 || Number(portfolio.market_value) !== 0) {
    metrics.push({
      label: "Invested equities",
      value: formatCurrency(portfolio.market_value, currency),
    });
  }

  if (portfolio.option_positions.length > 0 || Number(portfolio.options_market_value) !== 0) {
    metrics.push({
      label: "Options exposure",
      value: formatCurrency(portfolio.options_market_value, currency),
    });
  }

  if (
    hasInvestments &&
    analytics?.total_return_pct !== null &&
    analytics?.total_return_pct !== undefined
  ) {
    metrics.push({
      label: "All-history return",
      value: formatSignedPercent(analytics.total_return_pct),
      tone: toneFor(analytics.total_return_pct),
    });
  }

  if (hasInvestments && analytics?.sharpe_ratio !== null && analytics?.sharpe_ratio !== undefined) {
    metrics.push({ label: "Sharpe ratio", value: analytics.sharpe_ratio.toFixed(2) });
  }

  if (
    hasInvestments &&
    analytics?.max_drawdown_pct !== null &&
    analytics?.max_drawdown_pct !== undefined
  ) {
    metrics.push({
      label: "Max drawdown",
      value: formatSignedPercent(analytics.max_drawdown_pct),
      tone: "negative",
    });
  }

  return (
    <section aria-labelledby="portfolio-metrics-heading" className="mt-5">
      <h2 id="portfolio-metrics-heading" className="sr-only">
        Portfolio metrics
      </h2>
      <FigureStrip
        label="Portfolio metrics"
        figures={metrics.map((metric) => ({
          label: metric.label,
          note: metric.detail,
          value: (
            <span
              className={
                metric.tone === "positive"
                  ? "text-positive"
                  : metric.tone === "negative"
                    ? "text-negative"
                    : undefined
              }
            >
              {/* The arrow carries the sign as well as the colour. */}
              {metric.tone ? (
                <span aria-hidden>{metric.tone === "positive" ? "▲ " : "▼ "}</span>
              ) : null}
              <span>{metric.value}</span>
            </span>
          ),
        }))}
      />
      {hasInvestments && analytics?.history_days ? (
        <p className="mt-2 text-2xs text-muted-foreground">
          All-history risk metrics · Based on {analytics.history_days} daily snapshots
        </p>
      ) : null}
    </section>
  );
}

type Metric = {
  label: string;
  value: string;
  detail?: string;
  tone?: "positive" | "negative";
};

function toneFor(value: number): Metric["tone"] {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return undefined;
}
