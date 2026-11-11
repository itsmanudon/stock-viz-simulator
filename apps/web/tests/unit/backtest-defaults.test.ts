import { describe, expect, it } from "vitest";

import { defaultBacktestRange, pickBacktestTicker } from "@/lib/backtest-defaults";

describe("backtest defaults (UI audit F1)", () => {
  const symbols = [
    { ticker: "7203.T", name: "Toyota", lastClose: null },
    { ticker: "AAPL", name: "Apple", lastClose: "2025-04-04" },
  ];

  it("starts on the first symbol with stored history", () => {
    expect(pickBacktestTicker(symbols)).toBe("AAPL");
  });

  it("keeps a requested symbol even without history", () => {
    expect(pickBacktestTicker(symbols, "7203.T")).toBe("7203.T");
    expect(pickBacktestTicker(symbols, "NOPE")).toBe("AAPL");
  });

  it("falls back to the first symbol when history is unknown", () => {
    expect(
      pickBacktestTicker([
        { ticker: "B", name: "B" },
        { ticker: "C", name: "C" },
      ]),
    ).toBe("B");
  });

  it("ends a year of history at the latest close", () => {
    expect(defaultBacktestRange("2025-04-04")).toEqual({ from: "2024-04-04", to: "2025-04-04" });
  });

  it("ends at today without a close", () => {
    expect(defaultBacktestRange(null, new Date("2026-11-11T12:00:00Z"))).toEqual({
      from: "2025-11-11",
      to: "2026-11-11",
    });
  });
});
