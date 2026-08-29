import "server-only";

import {
  type DividendSummary,
  type PendingOrder,
  type Portfolio,
  type PortfolioAnalytics,
  type PortfolioHistoryPoint,
  getDividends,
  getPortfolio,
  getPortfolioAnalytics,
  getPortfolioHistory,
  listOrders,
} from "@/lib/api/trading";
import { type PortfolioRange, portfolioRangeDays } from "@/lib/portfolio-view-model";

export type PortfolioData = {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  analytics: PortfolioAnalytics | null;
  orders: PendingOrder[] | null;
  dividends: DividendSummary | null;
};

export async function loadPortfolioData(range: PortfolioRange): Promise<PortfolioData> {
  const [portfolio, history, analytics, orders, dividends] = await Promise.all([
    getPortfolio(),
    optional(getPortfolioHistory(portfolioRangeDays(range))),
    optional(getPortfolioAnalytics()),
    optional(listOrders("pending")),
    optional(getDividends()),
  ]);

  return { portfolio, history, analytics, orders, dividends };
}

function optional<T>(request: Promise<T>): Promise<T | null> {
  return request.catch(() => null);
}
