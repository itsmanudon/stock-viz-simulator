import { describe, expect, it } from "vitest";

import { STOCK_INDICATORS, chartLayers, parseStockIndicators } from "@/lib/stock-workspace";

const pt = [{ ts: "2026-11-11T00:00:00", value: 1 }];

describe("chartLayers (Phase 6.6)", () => {
  const bundle = {
    series: {
      sma_50: pt,
      "bb_20_2.upper": pt,
      "bb_20_2.middle": pt,
      "bb_20_2.lower": pt,
      "supertrend_10_3.line": pt,
      "supertrend_10_3.direction": pt,
      "stoch_14_3.k": pt,
      "stoch_14_3.d": pt,
      rsi_14: pt,
    },
    meta: {
      sma_50: { pane: "price", label: "SMA" },
      bb_20_2: { pane: "price", label: "Bollinger Bands" },
      supertrend_10_3: { pane: "price", label: "Supertrend" },
      stoch_14_3: { pane: "separate", label: "Stochastic" },
      rsi_14: { pane: "separate", label: "RSI" },
    },
  };

  it("places each indicator by its registry pane", () => {
    const { overlays, panes } = chartLayers(bundle, [
      "sma_50",
      "bb_20_2",
      "supertrend_10_3",
      "stoch_14_3",
      "rsi_14",
    ]);
    expect(Object.keys(overlays).sort()).toEqual([
      "bb_20_2.lower",
      "bb_20_2.middle",
      "bb_20_2.upper",
      "sma_50",
      "supertrend_10_3.line", // the direction state is not drawn as a line
    ]);
    expect(panes.map((p) => [p.name, Object.keys(p.lines)])).toEqual([
      ["stoch_14_3", ["stoch_14_3.k", "stoch_14_3.d"]],
    ]); // RSI keeps its own pane
  });

  it("ignores indicators that are not selected or not returned", () => {
    expect(chartLayers(bundle, ["adx_14"])).toEqual({ overlays: {}, panes: [] });
  });

  it("accepts every menu entry from the URL", () => {
    const all = STOCK_INDICATORS.map((i) => i.value);
    expect(parseStockIndicators(all.join(","))).toEqual(all);
  });
});
