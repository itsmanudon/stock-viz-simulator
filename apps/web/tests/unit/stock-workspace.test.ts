import { describe, expect, it } from "vitest";

import type { Bar } from "@/lib/api/types";
import {
  calculateAllocationPct,
  calculatePeriodReturnPct,
  calculatePositionReturnPct,
  deriveBarMetrics,
  estimateNotional,
  getBuyShortcutQuantity,
  getSellShortcutQuantity,
} from "@/lib/stock-workspace";

function bar(
  ts: string,
  open: string,
  high: string,
  low: string,
  close: string,
  volume: number,
): Bar {
  return { ts, open, high, low, close, volume };
}

describe("stock workspace financial calculations", () => {
  it("floors buy sizing to six decimals without spending beyond available cash", () => {
    expect(
      getBuyShortcutQuantity({
        availableCash: 100,
        price: 30,
        fraction: 1,
        symbolCurrency: "USD",
        displayCurrency: "USD",
      }),
    ).toBe("3.333333");
    expect(Number("3.333333") * 30).toBeLessThanOrEqual(100);
  });

  it("omits buy sizing when currencies differ or inputs are unusable", () => {
    expect(
      getBuyShortcutQuantity({
        availableCash: 100,
        price: 30,
        fraction: 0.5,
        symbolCurrency: "EUR",
        displayCurrency: "USD",
      }),
    ).toBeNull();
    expect(
      getBuyShortcutQuantity({
        availableCash: 100,
        price: 0,
        fraction: 0.5,
        symbolCurrency: "USD",
        displayCurrency: "USD",
      }),
    ).toBeNull();
  });

  it("sizes sells from shares available after reservations", () => {
    expect(getSellShortcutQuantity({ availableQuantity: 7.25, fraction: 0.5 })).toBe("3.625");
    expect(getSellShortcutQuantity({ availableQuantity: 0, fraction: 1 })).toBeNull();
  });

  it("estimates notional only from positive finite values", () => {
    expect(estimateNotional(2.5, 40)).toBe(100);
    expect(estimateNotional(0, 40)).toBeNull();
    expect(estimateNotional(2, Number.NaN)).toBeNull();
  });

  it("derives portfolio relationship percentages safely", () => {
    expect(calculatePositionReturnPct(25, 100)).toBe(25);
    expect(calculatePositionReturnPct(-10, 100)).toBe(-10);
    expect(calculatePositionReturnPct(10, 0)).toBeNull();
    expect(calculateAllocationPct(250, 1000)).toBe(25);
    expect(calculateAllocationPct(250, 0)).toBeNull();
  });

  it("calculates period return from the first close and latest authoritative close", () => {
    expect(calculatePeriodReturnPct(100, 110)).toBeCloseTo(10);
    expect(calculatePeriodReturnPct(0, 110)).toBeNull();
    expect(calculatePeriodReturnPct(null, 110)).toBeNull();
  });

  it("derives the latest session and trailing range from ordered bars", () => {
    const metrics = deriveBarMetrics([
      bar("2026-08-24", "100", "108", "97", "105", 1_000),
      bar("2026-08-25", "105", "112", "103", "110", 2_000),
      bar("2026-08-26", "110", "115", "109", "114", 3_000),
    ]);

    expect(metrics).toEqual({
      open: 110,
      high: 115,
      low: 109,
      previousClose: 110,
      volume: 3_000,
      rangeHigh: 115,
      rangeLow: 97,
      latestTimestamp: "2026-08-26",
    });
  });

  it("returns null metrics for an empty bar series", () => {
    expect(deriveBarMetrics([])).toEqual({
      open: null,
      high: null,
      low: null,
      previousClose: null,
      volume: null,
      rangeHigh: null,
      rangeLow: null,
      latestTimestamp: null,
    });
  });
});
