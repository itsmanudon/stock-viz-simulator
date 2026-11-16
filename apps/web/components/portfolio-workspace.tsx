import { Suspense } from "react";

import { JournalPanel } from "@/components/journal/journal-panel";
import { NewsList } from "@/components/news-list";
import { ExpirationView, OptionsGreeks } from "@/components/options-book";
import { PortfolioInsights } from "@/components/portfolio-analytics";
import { PortfolioEmptyState } from "@/components/portfolio-empty-state";
import { PortfolioAttributionPanel, PortfolioExposurePanel } from "@/components/portfolio-exposure";
import { PortfolioIncome } from "@/components/portfolio-income";
import { PortfolioMetrics } from "@/components/portfolio-metrics";
import { PortfolioOptions } from "@/components/portfolio-options";
import { PortfolioOrders } from "@/components/portfolio-orders";
import { PortfolioPerformance } from "@/components/portfolio-performance";
import { PortfolioPositions } from "@/components/portfolio-positions";
import { PortfolioReturnsPanel } from "@/components/portfolio-returns";
import { PortfolioRiskPanel } from "@/components/portfolio-risk";
import { PortfolioStrategies } from "@/components/portfolio-strategies";
import { PortfolioStressPanel } from "@/components/portfolio-stress";
import { PortfolioTabs } from "@/components/portfolio-tabs";
import { RebalancePreview } from "@/components/rebalance-preview";
import type { JournalMonth } from "@/lib/api/journal";
import type { OptionStrategy, OptionsBook } from "@/lib/api/options";
import type {
  DividendSummary,
  PendingOrder,
  Portfolio,
  PortfolioAnalytics,
  PortfolioHistoryPoint,
  PortfolioRisk,
  PortfolioStress,
} from "@/lib/api/trading";
import type { NewsArticle } from "@/lib/api/types";
import type { PortfolioRange, PortfolioTab } from "@/lib/portfolio-view-model";

type Props = {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  analytics: PortfolioAnalytics | null;
  orders: PendingOrder[] | null;
  dividends: DividendSummary | null;
  range: PortfolioRange;
  tab: PortfolioTab;
  journalMonth: JournalMonth | null;
  journalFailed: boolean;
  journalMonthKey: string;
  /** Aegis news for the holdings; only loaded while the News tab is open. */
  news?: NewsArticle[] | null;
  /** Phase 8.3 risk report; only loaded while the Analytics tab is open. */
  risk?: PortfolioRisk | null;
  /** Phase 8.4 stress tests; loaded with the risk report. */
  stress?: PortfolioStress | null;
  /** Phase 8.6: the goal value from the URL, for the risk panel's form. */
  goal?: number | null;
  /** Phase 9.5: the options book (Options and Analytics tabs). */
  optionsBook?: OptionsBook | null;
  /** Phase 9.5: strategies (Options tab). */
  strategies?: OptionStrategy[] | null;
};

export function PortfolioWorkspace({
  portfolio,
  history,
  analytics,
  orders,
  dividends,
  range,
  tab,
  journalMonth,
  journalFailed,
  journalMonthKey,
  news = null,
  risk = null,
  stress = null,
  goal = null,
  optionsBook = null,
  strategies = null,
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
    <div className="w-full px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <PortfolioPerformance portfolio={portfolio} history={history} range={range} tab={tab} />
      <PortfolioMetrics portfolio={portfolio} analytics={analytics} />

      <section aria-labelledby="portfolio-workspace-heading" className="mt-7">
        <h2 id="portfolio-workspace-heading" className="sr-only">
          Portfolio holdings and activity
        </h2>
        <PortfolioTabs
          activeTab={tab}
          range={range}
          positions={positions}
          options={
            <>
              <OptionsGreeks book={optionsBook} />
              <ExpirationView book={optionsBook} />
              <PortfolioStrategies strategies={strategies} />
              <PortfolioOptions
                positions={portfolio.option_positions}
                displayCurrency={displayCurrency}
              />
            </>
          }
          orders={<PortfolioOrders orders={orders} />}
          income={<PortfolioIncome dividends={dividends} positions={portfolio.positions} />}
          news={
            tab !== "news" ? null : !hasEquityPositions ? (
              <p className="py-6 text-sm text-muted-foreground">
                News about your holdings appears here once you hold a stock.
              </p>
            ) : news === null ? (
              <p className="py-6 text-sm text-muted-foreground">
                News is unavailable right now. Try again shortly.
              </p>
            ) : (
              <NewsList articles={news} />
            )
          }
          journal={
            /* JournalPanel reads Journal state with `useSearchParams()`, which
               Next requires to sit under a Suspense boundary — without one the
               whole tab subtree silently fails to hydrate and every calendar
               cell becomes inert HTML. */
            <Suspense fallback={<JournalPanelFallback />}>
              <JournalPanel
                initialMonthKey={journalMonthKey}
                initialMonth={journalMonth}
                initialError={journalFailed}
              />
            </Suspense>
          }
          analytics={
            <>
              <PortfolioReturnsPanel returns={analytics?.returns ?? null} />
              <PortfolioExposurePanel exposure={analytics?.exposure ?? null} />
              <PortfolioAttributionPanel attribution={analytics?.attribution ?? null} />
              {tab === "analytics" ? <OptionsGreeks book={optionsBook} /> : null}
              <PortfolioRiskPanel
                risk={risk}
                open={tab === "analytics"}
                goal={goal}
                range={range}
              />
              <PortfolioStressPanel stress={stress} open={tab === "analytics"} />
              {tab === "analytics" ? (
                <RebalancePreview
                  positions={portfolio.positions}
                  nav={Number(portfolio.total_value)}
                  currency={displayCurrency}
                />
              ) : null}
            </>
          }
          positionCount={portfolio.positions.length}
          optionCount={portfolio.option_positions.length}
          orderCount={orders?.length ?? 0}
        />
      </section>

      <PortfolioInsights analytics={analytics} hasEquityPositions={hasEquityPositions} />
    </div>
  );
}

/** Holds the Journal's vertical space while the client panel resolves. */
function JournalPanelFallback() {
  return <div className="min-h-[32rem]" aria-hidden />;
}
