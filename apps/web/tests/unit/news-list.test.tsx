import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NewsList, newsDateLabel } from "@/components/news-list";
import type { NewsArticle } from "@/lib/api";

const article = (overrides: Partial<NewsArticle> = {}): NewsArticle => ({
  id: "doc_1",
  tickers: ["AAPL", "MSFT"],
  title: "Apple widens supplier review",
  url: "https://news.example.test/1",
  source: "Reuters",
  published_at: "2025-04-04T13:00:00",
  available_at: "2025-04-05T02:00:00",
  sentiment: "mixed",
  sentiment_model: "lexicon-sentiment@1",
  topic: "business.supply_chain",
  ...overrides,
});

describe("NewsList (Aegis documents)", () => {
  it("dates by the publisher when there is one, else by collection (audit AG-12)", () => {
    expect(newsDateLabel(article())).toBe("Apr 4, 2025");
    expect(newsDateLabel(article({ published_at: null }))).toBe("Collected Apr 5, 2025");
  });

  it("links out, shows the mixed label and the linked tickers", () => {
    render(<NewsList articles={[article()]} />);
    expect(screen.getByRole("link", { name: /Apple widens supplier review/ })).toHaveAttribute(
      "href",
      "https://news.example.test/1",
    );
    expect(screen.getByLabelText("Sentiment: Mixed")).toBeVisible();
    expect(screen.getByText("AAPL · MSFT")).toBeVisible();
  });

  it("lists a document with no link as plain text", () => {
    render(<NewsList articles={[article({ url: null })]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Apple widens supplier review")).toBeVisible();
  });

  it("keeps the ticker list off the per-symbol workspace", () => {
    render(<NewsList articles={[article()]} variant="workspace" />);
    expect(screen.queryByText("AAPL · MSFT")).not.toBeInTheDocument();
  });
});
