import { describe, expect, it } from "vitest";

import type { Recommendation } from "@/lib/api";
import {
  buildSignalsHref,
  classifySignal,
  filterSignals,
  formatSignalDate,
  formatSignalDateTime,
  recommendationToSignal,
  sortSignals,
  votesFromRationale,
} from "@/lib/signals-workspace";

const rec = (overrides: Partial<Recommendation> = {}): Recommendation => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  sector: "Technology",
  score: 5,
  max_score: 7,
  rationale: ["Below historical mean ($70.00 < $88.00)"],
  votes: [],
  sentiment_7d: 0.3,
  computed_at: "2026-08-26T00:00:00Z",
  ...overrides,
});

describe("classifySignal", () => {
  it("treats score >= 4 as bullish and lower scores as neutral", () => {
    expect(classifySignal(4)).toBe("bullish");
    expect(classifySignal(3)).toBe("neutral");
    expect(classifySignal(0)).toBe("neutral");
  });
});

describe("votesFromRationale", () => {
  it("marks unmatched checks as not contributing", () => {
    const votes = votesFromRationale([
      "Below historical mean ($1 < $2)",
      "Volume above average (2 vs avg 1)",
    ]);
    const byId = Object.fromEntries(votes.map((vote) => [vote.id, vote]));
    expect(byId.below_mean.passed).toBe(true);
    expect(byId.volume_above_mean.passed).toBe(true);
    expect(byId.positive_sentiment.passed).toBe(false);
    expect(byId.positive_sentiment.detail).toContain("did not contribute");
  });
});

describe("recommendationToSignal", () => {
  it("uses structured votes when present and reconstructs them otherwise", () => {
    const withVotes = recommendationToSignal(
      rec({
        votes: [
          {
            id: "below_mean",
            label: "Below historical mean",
            passed: true,
            detail: "pass",
            available: true,
          },
          {
            id: "positive_sentiment",
            label: "Positive news sentiment",
            passed: false,
            detail: "none",
            available: true,
          },
        ],
      }),
    );
    expect(withVotes.signal).toBe("bullish");
    expect(withVotes.supportingVotes).toBe(1);
    expect(withVotes.votes).toHaveLength(7);

    const reconstructed = recommendationToSignal(rec({ votes: [] }));
    expect(reconstructed.votes).toHaveLength(7);
    expect(reconstructed.votes.find((vote) => vote.id === "below_mean")?.passed).toBe(true);
  });

  it("keeps missing sentiment as null", () => {
    expect(recommendationToSignal(rec({ sentiment_7d: null })).sentiment7d).toBeNull();
  });
});

describe("filter and sort", () => {
  const rows = [
    recommendationToSignal(rec({ ticker: "MSFT", name: "Microsoft", score: 2, sentiment_7d: 0.1 })),
    recommendationToSignal(rec({ ticker: "AAPL", score: 6, sentiment_7d: null })),
    recommendationToSignal(
      rec({ ticker: "XOM", name: "Exxon", sector: "Energy", score: 5, sentiment_7d: 0.8 }),
    ),
  ];

  it("filters by signal class, sector, and ticker query", () => {
    expect(filterSignals(rows, { signal: "bullish" }).map((row) => row.ticker)).toEqual([
      "AAPL",
      "XOM",
    ]);
    expect(filterSignals(rows, { sector: "Energy" }).map((row) => row.ticker)).toEqual(["XOM"]);
    expect(filterSignals(rows, { query: "micro" }).map((row) => row.ticker)).toEqual(["MSFT"]);
  });

  it("sorts by score, ticker, and sentiment with nulls last", () => {
    expect(sortSignals(rows, "ticker", "asc").map((row) => row.ticker)).toEqual([
      "AAPL",
      "MSFT",
      "XOM",
    ]);
    expect(sortSignals(rows, "sentiment", "desc").map((row) => row.ticker)).toEqual([
      "XOM",
      "MSFT",
      "AAPL",
    ]);
  });
});

describe("buildSignalsHref", () => {
  it("omits default filters so the all-signals URL stays clean", () => {
    expect(buildSignalsHref({})).toBe("/recommendations");
    expect(buildSignalsHref({ min: 4, signal: "bullish", q: "AAPL" })).toBe(
      "/recommendations?min=4&signal=bullish&q=AAPL",
    );
  });

  it("keeps a selected ticker shareable alongside filters and sorting", () => {
    expect(
      buildSignalsHref({
        min: 4,
        signal: "bullish",
        sort: "ticker",
        dir: "asc",
        selected: "AAPL",
      }),
    ).toBe("/recommendations?min=4&signal=bullish&sort=ticker&dir=asc&selected=AAPL");
  });
});

describe("signal dates", () => {
  it("shows the computed time in UTC and names the zone", () => {
    // 23:30 UTC is the next day east of UTC; the date must not move.
    expect(formatSignalDate("2025-04-04T23:30:00Z")).toBe("Apr 4, 2025");
    expect(formatSignalDateTime("2025-04-04T23:30:00Z")).toBe("Apr 4, 2025, 11:30 PM UTC");
  });
});

describe("the maximum follows the votes available (audit SR-9)", () => {
  it("reads six when the symbol has no scored news", () => {
    expect(recommendationToSignal(rec({ max_score: 6 })).maxScore).toBe(6);
  });

  it("falls back to seven for a response cached before the field existed", () => {
    const { max_score: _dropped, ...old } = rec();
    expect(recommendationToSignal(old as Recommendation).maxScore).toBe(7);
  });
});
