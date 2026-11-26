import { intradayTimeframe, priceRule, studyRule } from "@/lib/chart-menu";
// Owner, 27 Nov 2026: alerts made from an intraday chart are intraday rules.
import { describe, expect, it } from "vitest";

describe("intradayTimeframe", () => {
  it("is the chart's interval on intraday charts only", () => {
    for (const tf of ["1m", "5m", "15m", "30m", "60m"]) expect(intradayTimeframe(tf)).toBe(tf);
    for (const iv of ["1d", "1wk", "1mo", ""]) expect(intradayTimeframe(iv)).toBeNull();
  });
});

describe("priceRule", () => {
  it("crosses towards the level from the last close", () => {
    expect(priceRule("AAPL", 101.257, 100).rule).toBe("close crosses_above 101.26");
    expect(priceRule("AAPL", 95, 100).rule).toBe("close crosses_below 95.00");
  });
});

describe("studyRule", () => {
  it("names the same study the DSL reads", () => {
    expect(studyRule("AAPL", "sma_50", 110, 100)?.rule).toBe("close crosses_above sma(close, 50)");
    expect(studyRule("AAPL", "ema_20", 90, 100)?.rule).toBe("close crosses_below ema(close, 20)");
    expect(studyRule("AAPL", "bb_20_2.upper", 110, 100)?.rule).toBe(
      "close crosses_above bb(20, 2).upper",
    );
  });

  it("refuses a key it cannot turn into a call", () => {
    expect(studyRule("AAPL", "Weird-Key", 1, 1)).toBeNull();
    expect(studyRule("AAPL", "sma_x", 1, 1)).toBeNull();
  });
});
