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

  if (hasInvestments && analytics?.total_return_pct !== null && analytics?.total_return_pct !== undefined) {
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
    <section aria-labelledby="portfolio-metrics-heading" className="border-b border-border-muted">
      <h2 id="portfolio-metrics-heading" className="sr-only">
        Portfolio metrics
      </h2>
      <dl className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className="min-w-0 border-b border-border-muted px-3 py-4 even:border-l sm:px-4 lg:border-b-0 lg:border-l lg:first:border-l-0"
          >
            <dt className="text-[11px] font-medium text-muted-foreground">{metric.label}</dt>
            <dd
              className={`mt-1 font-mono text-base font-semibold ${
                metric.tone === "positive"
                  ? "text-positive"
                  : metric.tone === "negative"
                    ? "text-negative"
                    : "text-foreground"
              }`}
              data-financial
            >
              {metric.value}
            </dd>
            {metric.detail ? (
              <dd className="mt-0.5 text-[11px] text-muted-foreground">{metric.detail}</dd>
            ) : null}
          </div>
        ))}
      </dl>
      {hasInvestments && analytics?.history_days ? (
        <p className="border-t border-border-muted px-4 py-2 text-[11px] text-muted-foreground">
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
