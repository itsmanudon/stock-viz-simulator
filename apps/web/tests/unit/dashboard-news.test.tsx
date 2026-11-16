import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NewsWidget } from "@/components/dashboard/news-widget";
import type { NewsArticle } from "@/lib/api/types";
import { dashboardNewsTickers } from "@/lib/dashboard-news";

const article = (over: Partial<NewsArticle>): NewsArticle => ({
  id: "doc_1",
  tickers: ["AAPL"],
  title: "Apple shares rise after earnings",
  url: "https://example.com/apple",
  source: "Example Wire",
  published_at: "2026-11-14T00:00:00",
  available_at: "2026-11-14T03:00:00",
  sentiment: "positive",
  sentiment_model: "lexicon-sentiment@1",
  topic: null,
  ...over,
});

describe("dashboardNewsTickers", () => {
  it("takes holdings then the watchlist, upper-cased, each once", () => {
    expect(
      dashboardNewsTickers(
        [{ ticker: "aapl" }, { ticker: "MSFT" }],
        [{ ticker: "MSFT" }, { ticker: "TCS.NS" }],
      ),
    ).toEqual(["AAPL", "MSFT", "TCS.NS"]);
    expect(dashboardNewsTickers([], null)).toEqual([]);
  });
});

describe("NewsWidget", () => {
  it("lists headlines with only the account's own symbols, source and date", () => {
    render(
      <NewsWidget
        tickers={["AAPL"]}
        news={[
          article({ tickers: ["AAPL", "MSFT"] }),
          article({ id: "doc_2", url: null, title: "No link" }),
        ]}
      />,
    );
    const list = screen.getByRole("list", { name: "Headlines" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(
      within(items[0]).getByRole("link", { name: "Apple shares rise after earnings" }),
    ).toBeTruthy();
    expect(within(items[0]).getByRole("link", { name: "AAPL" }).getAttribute("href")).toBe(
      "/stocks/AAPL",
    );
    expect(within(items[0]).queryByText("MSFT")).toBeNull();
    expect(within(items[0]).getByText("Example Wire")).toBeTruthy();
    expect(within(items[1]).getByText("No link").tagName).toBe("P");
  });

  it("says why it is empty", () => {
    const { rerender } = render(<NewsWidget tickers={[]} news={[]} />);
    expect(screen.getByText(/Hold or watch a symbol/)).toBeTruthy();
    rerender(<NewsWidget tickers={["AAPL"]} news={[]} />);
    expect(screen.getByText(/No stored headlines about your holdings/)).toBeTruthy();
    rerender(<NewsWidget tickers={["AAPL"]} news={null} />);
    expect(screen.getByText(/News is unavailable/)).toBeTruthy();
  });
});
