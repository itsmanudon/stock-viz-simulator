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
