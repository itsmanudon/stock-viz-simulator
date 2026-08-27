import { PortfolioInsights } from "@/components/portfolio-analytics";
import { PortfolioEmptyState } from "@/components/portfolio-empty-state";
import { PortfolioIncome } from "@/components/portfolio-income";
import { PortfolioMetrics } from "@/components/portfolio-metrics";
import { PortfolioOptions } from "@/components/portfolio-options";
import { PortfolioOrders } from "@/components/portfolio-orders";
import { PortfolioPerformance } from "@/components/portfolio-performance";
import { PortfolioPositions } from "@/components/portfolio-positions";
import { PortfolioTabs } from "@/components/portfolio-tabs";
import type {
  DividendSummary,
  PendingOrder,
  Portfolio,
  PortfolioAnalytics,
  PortfolioHistoryPoint,
} from "@/lib/api/trading";
import type { PortfolioRange, PortfolioTab } from "@/lib/portfolio-view-model";

type Props = {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  analytics: PortfolioAnalytics | null;
  orders: PendingOrder[] | null;
  dividends: DividendSummary | null;
  range: PortfolioRange;
  tab: PortfolioTab;
};

export function PortfolioWorkspace({
  portfolio,
  history,
  analytics,
  orders,
  dividends,
  range,
  tab,
}: Props) {
  const displayCurrency = portfolio.display_currency || "USD";
  const hasEquityPositions = portfolio.positions.length > 0;
  const hasInvestments = hasEquityPositions || portfolio.option_positions.length > 0;

  const positions = hasInvestments ? (
    <PortfolioPositions
      positions={portfolio.positions}
      displayCurrency={displayCurrency}
      totalValue={portfolio.total_value}
    />
  ) : (
    <PortfolioEmptyState
      availableCash={portfolio.available_cash}
      displayCurrency={displayCurrency}
    />
  );

  return (
    <div className="w-full px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <PortfolioPerformance portfolio={portfolio} history={history} range={range} tab={tab} />
      <PortfolioMetrics portfolio={portfolio} analytics={analytics} />

      <section aria-labelledby="portfolio-workspace-heading" className="mt-8">
        <h2 id="portfolio-workspace-heading" className="sr-only">
          Portfolio holdings and activity
        </h2>
        <PortfolioTabs
          activeTab={tab}
          range={range}
          positions={positions}
          options={
            <PortfolioOptions
              positions={portfolio.option_positions}
              displayCurrency={displayCurrency}
            />
          }
          orders={<PortfolioOrders orders={orders} />}
          income={<PortfolioIncome dividends={dividends} positions={portfolio.positions} />}
          optionCount={portfolio.option_positions.length}
          orderCount={orders?.length ?? 0}
        />
      </section>

      <PortfolioInsights analytics={analytics} hasEquityPositions={hasEquityPositions} />
    </div>
  );
}
