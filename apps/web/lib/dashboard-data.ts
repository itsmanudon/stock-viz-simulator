import "server-only";

import { type Alert, listAlerts } from "@/lib/api/alerts";
import { getNewsForTickers } from "@/lib/api/news";
import {
  type PendingOrder,
  type Portfolio,
  type PortfolioAnalytics,
  type PortfolioHistoryPoint,
  getPortfolioHistory,
  listOrders,
} from "@/lib/api/trading";
import type { NewsArticle } from "@/lib/api/types";
import { type WatchlistItem, listWatchlist } from "@/lib/api/watchlist";
import { DASHBOARD_NEWS_LIMIT, dashboardNewsTickers } from "@/lib/dashboard-news";
import { loadPortfolioOverview } from "@/lib/portfolio-overview";
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
  /** Watchlist and alert rows carry their own currency. */
  watchlist: WatchlistItem[] | null;
  /** Headlines linked to a holding or a watchlist symbol; null when the call failed. */
  news: NewsArticle[] | null;
  /** The symbols `news` was asked for: holdings first, then the watchlist. */
  newsTickers: string[];
};

export async function loadDashboardData(): Promise<DashboardData> {
  const [overview, history, orders, alerts, watchlist] = await Promise.all([
    loadPortfolioOverview(),
    optional(getPortfolioHistory(DASHBOARD_HISTORY_DAYS)),
    optional(listOrders("pending")),
    optional(listAlerts()),
    optional(listWatchlist()),
  ]);

  // News needs the holdings and the watchlist, so it is the one second call.
  const newsTickers = dashboardNewsTickers(overview.portfolio.positions, watchlist);
  const news =
    newsTickers.length === 0
      ? []
      : await optional(getNewsForTickers(newsTickers, DASHBOARD_NEWS_LIMIT));

  return { ...overview, history, orders, alerts, watchlist, news, newsTickers };
}

function optional<T>(request: Promise<T>): Promise<T | null> {
  return request.catch(() => null);
}
