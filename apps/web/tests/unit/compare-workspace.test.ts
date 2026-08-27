import { describe, expect, it } from "vitest";

import type { CompareMetrics } from "@/lib/compare-workspace";
import {
  annualizedVolatilityPct,
  buildCompareHref,
  deriveCompareInsights,
  maxDrawdownPct,
  parseCompareSearchParams,
  parseCompareTickers,
  rangeReturnPct,
  week52PositionPct,
} from "@/lib/compare-workspace";

function row(overrides: Partial<CompareMetrics>): CompareMetrics {
  return {
    ticker: "AAPL",
    name: "Apple Inc.",
    sector: "Technology",
    color: "#3b82f6",
    bars: [],
    lastPrice: 100,
    returnPct: 10,
    volatilityPct: 20,
    maxDrawdownPct: 5,
    rsi14: 55,
    week52PositionPct: 70,
    sentiment7d: 0.2,
    ...overrides,
  };
}

describe("parseCompareTickers", () => {
  it("returns an empty list when no query is present", () => {
    expect(parseCompareTickers(undefined)).toEqual([]);
    expect(parseCompareTickers("")).toEqual([]);
  });

  it("dedupes, uppercases, and caps at six symbols", () => {
    expect(parseCompareTickers("aapl, AAPL, msft, goog, amzn, meta, nvda, tsla")).toEqual([
      "AAPL",
      "MSFT",
      "GOOG",
      "AMZN",
      "META",
      "NVDA",
    ]);
  });
});

describe("parseCompareSearchParams", () => {
  it("accepts the symbols alias and defaults the window to 1Y", () => {
    expect(parseCompareSearchParams({ symbols: "aapl,msft" })).toEqual({
      tickers: ["AAPL", "MSFT"],
      timeframe: "1Y",
    });
  });

  it("prefers tickers over symbols and preserves tf", () => {
    expect(parseCompareSearchParams({ tickers: "NVDA", symbols: "AAPL", tf: "3M" })).toEqual({
      tickers: ["NVDA"],
      timeframe: "3M",
    });
  });
});

describe("window statistics", () => {
  it("computes return, volatility, drawdown, and 52-week position from closes", () => {
    expect(rangeReturnPct([100, 110])).toBeCloseTo(10);
    expect(annualizedVolatilityPct([100, 100, 100])).toBe(0);
    expect(maxDrawdownPct([100, 120, 90])).toBeCloseTo(25);
    expect(week52PositionPct(125, 100, 150)).toBeCloseTo(50);
  });

  it("returns null for partial series", () => {
    expect(rangeReturnPct([100])).toBeNull();
    expect(annualizedVolatilityPct([100, 110])).toBeNull();
    expect(maxDrawdownPct([100])).toBeNull();
    expect(week52PositionPct(null, 100, 150)).toBeNull();
  });
});

describe("buildCompareHref", () => {
  it("keeps tickers and timeframe in the URL", () => {
    expect(buildCompareHref(["AAPL", "MSFT"], "6M")).toBe("/compare?tickers=AAPL%2CMSFT&tf=6M");
  });
});

describe("deriveCompareInsights", () => {
  it("asks for a second symbol when only one is selected", () => {
    const insights = deriveCompareInsights([
      row({
        ticker: "AAPL",
        returnPct: 8.2,
        bars: [{ ts: "1", open: "1", high: "1", low: "1", close: "1", volume: 1 }],
      }),
    ]);
    expect(insights[0]?.id).toBe("single-symbol");
    expect(insights.some((item) => item.id === "single-return")).toBe(true);
  });

  it("reports leader, laggard, RSI, sentiment, and shared sector", () => {
    const insights = deriveCompareInsights([
      row({ ticker: "AAPL", returnPct: 12, rsi14: 30, sentiment7d: 0.4 }),
      row({ ticker: "MSFT", returnPct: -3, rsi14: 70, sentiment7d: -0.1, bars: [] }),
    ]);
    const byId = Object.fromEntries(insights.map((item) => [item.id, item.text]));
    expect(byId.leader).toContain("AAPL led");
    expect(byId.laggard).toContain("MSFT lagged");
    expect(byId.rsi).toContain("MSFT has the highest RSI");
    expect(byId.sentiment).toContain("AAPL has the strongest");
    expect(byId.sectors).toContain("Technology");
    expect(byId["missing-history"]).toContain("MSFT");
  });
});
