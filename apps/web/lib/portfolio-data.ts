import "server-only";

import { type JournalMonth, getJournalMonth } from "@/lib/api/journal";
import {
  type DividendSummary,
  type PendingOrder,
  type Portfolio,
  type PortfolioAnalytics,
  type PortfolioHistoryPoint,
  getDividends,
  getPortfolioHistory,
  listOrders,
} from "@/lib/api/trading";
import { splitMonthKey } from "@/lib/journal-view-model";
import { loadPortfolioOverview } from "@/lib/portfolio-overview";
import { type PortfolioRange, portfolioRangeDays } from "@/lib/portfolio-view-model";

export type PortfolioData = {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  analytics: PortfolioAnalytics | null;
  orders: PendingOrder[] | null;
  dividends: DividendSummary | null;
  /** Only fetched when the Journal tab is open; null on the other tabs. */
  journalMonth: JournalMonth | null;
  /** True when the Journal tab was open and its request failed. */
  journalFailed: boolean;
};

/**
 * The portfolio page's data, fanned out in one round.
 *
 * ``journalMonthKey`` is passed only when the Journal tab is the one being
 * rendered — the calendar is a tab, not a header, so a user on Positions
 * shouldn't pay for a month of journal aggregation on every page load.
 */
export async function loadPortfolioData(
  range: PortfolioRange,
  journalMonthKey?: string,
): Promise<PortfolioData> {
  const journalRequest = journalMonthKey
    ? optional(
        getJournalMonth(splitMonthKey(journalMonthKey).year, splitMonthKey(journalMonthKey).month),
      )
    : Promise.resolve(null);

  const [overview, history, orders, dividends, journalMonth] = await Promise.all([
    loadPortfolioOverview(),
    optional(getPortfolioHistory(portfolioRangeDays(range))),
    optional(listOrders("pending")),
    optional(getDividends()),
    journalRequest,
  ]);

  return {
    portfolio: overview.portfolio,
    history,
    analytics: overview.analytics,
    orders,
    dividends,
    journalMonth,
    journalFailed: Boolean(journalMonthKey) && journalMonth === null,
  };
}

function optional<T>(request: Promise<T>): Promise<T | null> {
  return request.catch(() => null);
}
