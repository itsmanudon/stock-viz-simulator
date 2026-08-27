import { describe, expect, it } from "vitest";

import type { Recommendation } from "@/lib/api";
import {
  buildSignalsHref,
  classifySignal,
  filterSignals,
  recommendationToSignal,
  sortSignals,
  votesFromRationale,
} from "@/lib/signals-workspace";

const rec = (overrides: Partial<Recommendation> = {}): Recommendation => ({
  ticker: "AAPL",
  name: "Apple Inc.",
  sector: "Technology",
  score: 5,
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
          { id: "below_mean", label: "Below historical mean", passed: true, detail: "pass" },
          {
            id: "positive_sentiment",
            label: "Positive news sentiment",
            passed: false,
            detail: "none",
          },
        ],
      }),
    );
    expect(withVotes.signal).toBe("bullish");
    expect(withVotes.supportingVotes).toBe(1);

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
});
