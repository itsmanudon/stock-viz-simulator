import "server-only";

import { listSymbols } from "@/lib/api";
import { type Alert, listAlerts } from "@/lib/api/alerts";
import {
  type PendingOrder,
  type Portfolio,
  type PortfolioAnalytics,
  type PortfolioHistoryPoint,
  getPortfolioHistory,
  listOrders,
} from "@/lib/api/trading";
import { type WatchlistItem, listWatchlist } from "@/lib/api/watchlist";
import { currencyByTicker } from "@/lib/operational-trading";
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
  watchlist: WatchlistItem[] | null;
  /** Trading currency per ticker; watchlist and alert rows carry none. */
  currencies: Record<string, string>;
};

export async function loadDashboardData(): Promise<DashboardData> {
  const [overview, history, orders, alerts, watchlist, symbols] = await Promise.all([
    loadPortfolioOverview(),
    optional(getPortfolioHistory(DASHBOARD_HISTORY_DAYS)),
    optional(listOrders("pending")),
    optional(listAlerts()),
    optional(listWatchlist()),
    // Without it prices still show, as USD, the same fallback /watchlist uses.
    optional(listSymbols()),
  ]);

  const currencies = currencyByTicker(symbols ?? []);
  return { ...overview, history, orders, alerts, watchlist, currencies };
}

function optional<T>(request: Promise<T>): Promise<T | null> {
  return request.catch(() => null);
}
