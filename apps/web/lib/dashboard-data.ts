import "server-only";

import { type Alert, listAlerts } from "@/lib/api/alerts";
import {
  type PendingOrder,
  type Portfolio,
  type PortfolioAnalytics,
  type PortfolioHistoryPoint,
  getPortfolio,
  getPortfolioAnalytics,
  getPortfolioHistory,
  listOrders,
} from "@/lib/api/trading";
import { type WatchlistItem, listWatchlist } from "@/lib/api/watchlist";
import { DASHBOARD_HISTORY_DAYS } from "@/lib/portfolio-view-model";

/**
 * Everything the signed-in dashboard renders.
 *
 * The portfolio itself is the only required call — without it there is no
 * dashboard to draw. Every other widget degrades to its own empty state when
 * its request fails, so one flaky endpoint can't blank the whole page.
 */
export type DashboardData = {
  portfolio: Portfolio;
  history: PortfolioHistoryPoint[] | null;
  analytics: PortfolioAnalytics | null;
  orders: PendingOrder[] | null;
  alerts: Alert[] | null;
  watchlist: WatchlistItem[] | null;
};

export async function loadDashboardData(): Promise<DashboardData> {
  const [portfolio, history, analytics, orders, alerts, watchlist] = await Promise.all([
    getPortfolio(),
    optional(getPortfolioHistory(DASHBOARD_HISTORY_DAYS)),
    optional(getPortfolioAnalytics()),
    optional(listOrders("pending")),
    optional(listAlerts()),
    optional(listWatchlist()),
  ]);

  return { portfolio, history, analytics, orders, alerts, watchlist };
}

function optional<T>(request: Promise<T>): Promise<T | null> {
  return request.catch(() => null);
}
