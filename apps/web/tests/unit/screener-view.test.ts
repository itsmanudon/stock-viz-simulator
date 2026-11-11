import { describe, expect, it } from "vitest";

import type { ScreenerResult } from "@/lib/api/types";
import {
  activeFilterChips,
  clearFiltersHref,
  parseScreenerSort,
  screenerSortHref,
  sortScreenerRows,
} from "@/lib/screener-view";

function row(ticker: string, over: Partial<ScreenerResult> = {}): ScreenerResult {
  return {
    ticker,
    name: ticker,
    sector: null,
    exchange: null,
    currency: "USD",
    last_close: "100",
    as_of: "2025-03-01",
    rsi_14: 50,
    momentum_pct: null,
    momentum_days: null,
    high_52w: "120",
    low_52w: "80",
    sentiment_7d: null,
    ...over,
  };
}

describe("activeFilterChips", () => {
  it("shows nothing when no filter is applied", () => {
    expect(activeFilterChips({ sort: "rsi", dir: "asc" })).toEqual([]);
  });

  it("joins the two RSI bounds into one chip that removes both", () => {
    const [chip] = activeFilterChips({ rsi_min: "30", rsi_max: "70", sector: "Energy" }).filter(
      (c) => c.id === "rsi",
    );
    expect(chip.label).toBe("RSI 30 to 70");
    expect(chip.removeHref).toBe("/screener?sector=Energy");
  });

  it("names one-sided bounds", () => {
    const labels = activeFilterChips({ rsi_max: "30" }).map((c) => c.label);
    expect(labels).toEqual(["RSI at most 30"]);
  });

  it("gives momentum bounds no chip without a window, as the API ignores them", () => {
    expect(activeFilterChips({ momentum_min: "5" })).toEqual([]);
    const [chip] = activeFilterChips({ momentum_days: "20", momentum_min: "5" });
    expect(chip.label).toBe("20-day momentum at least 5%");
    expect(chip.removeHref).toBe("/screener");
  });

  it("keeps the sort when a chip is removed, unless it sorted by that chip", () => {
    const keep = activeFilterChips({ sector: "Energy", sort: "rsi", dir: "asc" });
    expect(keep[0].removeHref).toBe("/screener?sort=rsi&dir=asc");
    const drop = activeFilterChips({ momentum_days: "20", sort: "momentum", dir: "desc" });
    expect(drop[0].removeHref).toBe("/screener");
  });

  it("clears every filter but keeps the sort", () => {
    expect(clearFiltersHref({ sector: "Energy", near_52w_high: "true", sort: "price" })).toBe(
      "/screener?sort=price",
    );
  });
});

describe("screener sort", () => {
  it("falls back to ticker A-Z, and refuses a momentum sort without a window", () => {
    expect(parseScreenerSort({})).toEqual({ sort: "ticker", dir: "asc" });
    expect(parseScreenerSort({ sort: "momentum" })).toEqual({ sort: "ticker", dir: "asc" });
    expect(parseScreenerSort({ sort: "momentum", momentum_days: "20" })).toEqual({
      sort: "momentum",
      dir: "desc",
    });
  });

  it("sorts numbers biggest first on the first click and flips on the second", () => {
    expect(screenerSortHref("rsi", { sector: "Energy" })).toBe(
      "/screener?sector=Energy&sort=rsi&dir=desc",
    );
    expect(screenerSortHref("rsi", { sort: "rsi", dir: "desc" })).toBe(
      "/screener?sort=rsi&dir=asc",
    );
  });

  it("puts missing values last in both directions", () => {
    const rows = [row("A", { rsi_14: null }), row("B", { rsi_14: 20 }), row("C", { rsi_14: 80 })];
    expect(sortScreenerRows(rows, "rsi", "desc").map((r) => r.ticker)).toEqual(["C", "B", "A"]);
    expect(sortScreenerRows(rows, "rsi", "asc").map((r) => r.ticker)).toEqual(["B", "C", "A"]);
  });

  it("sorts price by the number, not the string", () => {
    const rows = [row("A", { last_close: "9.5" }), row("B", { last_close: "100" })];
    expect(sortScreenerRows(rows, "price", "desc").map((r) => r.ticker)).toEqual(["B", "A"]);
  });
});
