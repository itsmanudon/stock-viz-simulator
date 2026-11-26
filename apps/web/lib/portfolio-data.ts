import {
  type OptionStrategy,
  type OptionsBook,
  getOptionsBook,
  listStrategies,
} from "@/lib/api/options";
import "server-only";

import { getNewsForTickers } from "@/lib/api";
import { type JournalMonth, getJournalMonth } from "@/lib/api/journal";
import { listPlans } from "@/lib/api/plans";
import {
  type DividendSummary,
  type PendingOrder,
  type Portfolio,
  type PortfolioAnalytics,
  type PortfolioHistoryPoint,
  type PortfolioRisk,
  type PortfolioStress,
  getDividends,
  getPortfolioHistory,
  getPortfolioRisk,
  getPortfolioStress,
  listOrders,
} from "@/lib/api/trading";
import type { NewsArticle } from "@/lib/api/types";
import type { BookRef } from "@/lib/book-url";
import { splitMonthKey } from "@/lib/journal-view-model";
import type { TradePlan } from "@/lib/plans";
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
  /**
   * Aegis news for the held symbols. Only fetched when the News tab is open;
   * null on the other tabs or when the request failed (Phase 2).
   */
  news: NewsArticle[] | null;
  /** Phase 8.3: only fetched when the Analytics tab is open; null otherwise or on failure. */
  risk: PortfolioRisk | null;
  /** Phase 8.4: fetched with the risk report, on the Analytics tab only. */
  stress: PortfolioStress | null;
  /** Phase 9.5: the options book; on the Options and Analytics tabs only. */
  optionsBook: OptionsBook | null;
  /** Phase 9.5: strategies; on the Options tab only. */
  strategies: OptionStrategy[] | null;
  /** A5.4: the book's trade plans; on the Journal tab of one book only. */
  plans: TradePlan[] | null;
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
  {
    news: wantNews = false,
    risk: wantRisk = false,
    goal = null,
    options: wantOptions = false,
    book = null,
    plansBook = null,
  }: {
    news?: boolean;
    risk?: boolean;
    goal?: number | null;
    options?: boolean;
    /** A5.2: the book id, `"all"` or null (default). */
    book?: BookRef | null;
    /** A5.4: the resolved book whose plans the Journal tab lists (null: none). */
    plansBook?: number | null;
  } = {},
): Promise<PortfolioData> {
  // All books has no journal, risk, stress, dividends or options view: those
  // are per book (the API's `?book=` takes an id there, never `all`).
  const all = book === "all";
  const one = all ? null : book;
  const journalRequest =
    journalMonthKey && !all
      ? optional(
          getJournalMonth(
            splitMonthKey(journalMonthKey).year,
            splitMonthKey(journalMonthKey).month,
            one,
          ),
        )
      : Promise.resolve(null);

  const [
    overview,
    history,
    orders,
    dividends,
    journalMonth,
    risk,
    stress,
    optionsBook,
    strategies,
    plans,
  ] = await Promise.all([
    loadPortfolioOverview(book),
    optional(getPortfolioHistory(portfolioRangeDays(range), book)),
    optional(listOrders("pending", book)),
    all ? Promise.resolve(null) : optional(getDividends(one)),
    journalRequest,
    wantRisk && !all ? optional(getPortfolioRisk(goal, one)) : Promise.resolve(null),
    wantRisk && !all ? optional(getPortfolioStress(one)) : Promise.resolve(null),
    (wantOptions || wantRisk) && !all ? optional(getOptionsBook(one)) : Promise.resolve(null),
    wantOptions && !all ? optional(listStrategies(one)) : Promise.resolve(null),
    journalMonthKey && !all && plansBook
      ? optional(listPlans(plansBook).then((r) => r.plans))
      : Promise.resolve(null),
  ]);

  // Needs the holdings, so it follows the overview rather than joining it.
  const news = wantNews
    ? await optional(
        getNewsForTickers(overview.portfolio.positions.map((position) => position.ticker)),
      )
    : null;

  return {
    portfolio: overview.portfolio,
    history,
    analytics: overview.analytics,
    orders,
    dividends,
    journalMonth,
    journalFailed: Boolean(journalMonthKey) && !all && journalMonth === null,
    news,
    risk,
    stress,
    optionsBook,
    strategies,
    plans,
  };
}

function optional<T>(request: Promise<T>): Promise<T | null> {
  return request.catch(() => null);
}
