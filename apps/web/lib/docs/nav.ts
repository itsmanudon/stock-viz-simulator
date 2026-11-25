/**
 * The public user guide at /docs: its sections and pages, in reading order.
 * Every page here has content in `components/docs/pages`; the sidebar, the
 * overview, the previous/next links and the e2e check all read this list.
 */

export type DocPage = {
  slug: string;
  title: string;
  /** One sentence for the overview card and the page's meta description. */
  summary: string;
};

export type DocSection = { title: string; pages: DocPage[] };

export const DOC_SECTIONS: DocSection[] = [
  {
    title: "Start here",
    pages: [
      {
        slug: "getting-started",
        title: "Getting started",
        summary:
          "Your paper account, what end-of-day and simulated mean here, and where everything is.",
      },
    ],
  },
  {
    title: "Trading",
    pages: [
      {
        slug: "orders",
        title: "Orders",
        summary:
          "Market, limit, stop-loss and take-profit orders: when they fill, at what price, and what they hold back.",
      },
      {
        slug: "options",
        title: "Options",
        summary:
          "Buying calls and puts, writing covered ones, how they are priced, the Greeks, and what happens at expiry.",
      },
      {
        slug: "option-strategies",
        title: "Option strategies",
        summary:
          "Spreads, iron condors, straddles and calendars from templates: the builder, the payoff and settlement.",
      },
    ],
  },
  {
    title: "Research",
    pages: [
      {
        slug: "markets-and-stocks",
        title: "Markets and stock pages",
        summary:
          "Every symbol's latest close, and a stock's chart, indicators, financials and news.",
      },
      {
        slug: "screener-and-compare",
        title: "Screener and compare",
        summary:
          "Filter the universe on technicals and fundamentals, and compare symbols side by side.",
      },
      {
        slug: "signals",
        title: "Signals",
        summary:
          "Seven explainable votes per symbol, what makes a signal bullish, and what it is not.",
      },
      {
        slug: "backtests",
        title: "Backtests",
        summary:
          "Replay a rule over history with honest fills and costs, save runs, walk forward and sweep.",
      },
      {
        slug: "news-reactions",
        title: "News and news reactions",
        summary: "Where the news comes from, and how stocks moved around news of one kind.",
      },
      {
        slug: "replay",
        title: "Replay",
        summary: "Trade a past stretch of history bar by bar without seeing what comes next.",
      },
    ],
  },
  {
    title: "Portfolio and risk",
    pages: [
      {
        slug: "portfolio",
        title: "Portfolio",
        summary: "The headline figures, each tab and the daily history.",
      },
      {
        slug: "returns-and-risk",
        title: "Returns and risk",
        summary:
          "Time- and money-weighted returns, exposure, value at risk, stress tests and goals.",
      },
      {
        slug: "alerts",
        title: "Alerts and notifications",
        summary:
          "Price, technical, news and portfolio rules, when they fire, and what notifies you.",
      },
    ],
  },
  {
    title: "Reference",
    pages: [
      {
        slug: "how-figures-are-measured",
        title: "How figures are measured",
        summary: "Where prices and rates come from, and the method behind each figure.",
      },
      {
        slug: "glossary-and-faq",
        title: "Glossary and FAQ",
        summary: "The terms used here, and answers to the questions people ask most.",
      },
    ],
  },
];

export const DOC_PAGES: DocPage[] = DOC_SECTIONS.flatMap((section) => section.pages);

export function findDocPage(slug: string): DocPage | undefined {
  return DOC_PAGES.find((page) => page.slug === slug);
}

/** The pages before and after ``slug`` in reading order. */
export function neighbours(slug: string): { previous?: DocPage; next?: DocPage } {
  const index = DOC_PAGES.findIndex((page) => page.slug === slug);
  if (index < 0) return {};
  return { previous: DOC_PAGES[index - 1], next: DOC_PAGES[index + 1] };
}
