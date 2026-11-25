import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IndicatorMenu, StudyEditor, keyFor } from "@/components/indicator-menu";
import { PriceChart, groupLegend } from "@/components/price-chart";
import { StockChartToolbar } from "@/components/stock-chart-toolbar";
import type { ChecklistEvidence, IndicatorCatalogItem, IndicatorParam } from "@/lib/api/types";
import { allPanes } from "@/lib/chart-panes";
import { badgesFor, indicatorBadge } from "@/lib/indicator-badge";
import {
  STOCK_INDICATORS,
  buildIndicatorKey,
  chartLayers,
  indicatorLabel,
  macdSeries,
  paramError,
  parseStockIndicators,
} from "@/lib/stock-workspace";

import { lwcCalls, resetLwc } from "../stubs/lightweight-charts";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const int = (name: string, d: number, min = 1, max = 500): IndicatorParam => ({
  name,
  label: name,
  type: "int",
  default: d,
  min,
  max,
  min_exclusive: false,
  step: 1,
  choices: [],
});
const float = (name: string, d: number, max: number): IndicatorParam => ({
  name,
  label: name,
  type: "float",
  default: d,
  min: 0,
  max,
  min_exclusive: true,
  step: max <= 1 ? 0.01 : 0.1,
  choices: [],
});

const EVIDENCE: ChecklistEvidence = {
  grade: "C",
  n_events: 412,
  symbols: 25,
  horizon: 20,
  window_start: "2016-11-25",
  window_end: "2026-11-25",
  mean_excess: 0.0031,
  t_stat: 1.4,
  hit_rate: 0.52,
  mean_net_return: 0.012,
  base_rate: 0.009,
  overlapping_skipped: 3,
  universe: {
    name: "pinned",
    point_in_time: false,
    survivorship_biased: true,
    note: "Graded on the pinned symbol list.",
  },
  computed_at: "2026-11-26T03:00:00",
};

function item(
  key: string,
  label: string,
  parameters: IndicatorParam[],
  extra: Partial<IndicatorCatalogItem> = {},
): IndicatorCatalogItem {
  return {
    key,
    label,
    params: parameters.map((p) => p.name),
    defaults: parameters.map((p) => p.default),
    outputs: ["value"],
    pane: "separate",
    group: "momentum",
    parameters,
    default_key: [key, ...parameters.map((p) => p.default)].join("_"),
    anchored: "none",
    description: "",
    source: "",
    signal: null,
    ...extra,
  };
}

const RSI_SIGNAL = {
  rule: "rsi(14) crosses_above 30",
  hash: "h",
  description: "RSI(14) crosses up through 30",
  source: "",
  evidence: EVIDENCE,
};
const RSI = item("rsi", "RSI", [int("n", 14)], {
  signal: {
    rule: "rsi(14) crosses_above 30",
    hash: "h",
    description: "RSI(14) crosses up through 30",
    source: "",
    evidence: EVIDENCE,
  },
});
const BB = item("bb", "Bollinger Bands", [int("n", 20), float("k", 2, 10)], { pane: "price" });
const PSAR = item("psar", "Parabolic SAR", [float("step", 0.02, 0.5), float("max", 0.2, 1)], {
  default_key: "psar_0.02_0.2",
});
const PIVOTS = item("pivots", "Pivot points (classic)", [
  { ...int("basis", 3, 1, 4), choices: ["bar", "week", "month", "year"] },
]);
const MACD = item("macd", "MACD", [int("fast", 12), int("slow", 26), int("signal", 9)]);
const CATALOG = [RSI, BB, PSAR, PIVOTS, MACD];
const BOUNDS = Object.fromEntries(CATALOG.map((c) => [c.key, c.parameters]));

beforeEach(() => {
  push.mockReset();
  resetLwc();
});

describe("chart keys (A3.4)", () => {
  it("builds keys in the API's grammar", () => {
    expect(buildIndicatorKey("bb", [20, 2.5])).toBe("bb_20_2.5");
    expect(buildIndicatorKey("psar", [0.02, 0.2])).toBe("psar_0.02_0.2");
    expect(buildIndicatorKey("rsi", [21])).toBe("rsi_21");
    expect(keyFor(MACD, [12, 26, 9])).toBe("macd");
    expect(keyFor(MACD, [8, 21, 5])).toBe("macd_8_21_5");
  });

  it("labels a key by its study and values", () => {
    expect(indicatorLabel("bb_20_2.5")).toBe("Bollinger Bands 20, 2.5");
    expect(indicatorLabel("rsi_21")).toBe("RSI 21");
    expect(indicatorLabel("obv")).toBe("OBV");
  });

  it("keeps in-bounds keys from the URL and drops the rest", () => {
    expect(
      parseStockIndicators(
        "rsi_21,rsi_0,bb_20_2.5,bb_20_11,psar,pivots_9,macd_12_26_9,rsi_21",
        BOUNDS,
      ),
    ).toEqual(["rsi_21", "bb_20_2.5", "psar_0.02_0.2", "macd"]);
    // Without the catalog: a known study with no more parameters than it takes.
    expect(parseStockIndicators("rsi_21,rsi_14_3,nope_1,obv")).toEqual(["rsi_21", "obv"]);
  });

  it("explains a value out of bounds", () => {
    expect(paramError(int("n", 14), 0)).toBe("n must be a whole number from 1 to 500");
    expect(paramError(int("n", 14), 2.5)).toBe("n must be a whole number from 1 to 500");
    expect(paramError(float("k", 2, 10), 0)).toBe("k must be above 0 and at most 10");
    expect(paramError(float("k", 2, 10), 2.5)).toBeNull();
  });

  it("lists every registry study once", () => {
    const keys = STOCK_INDICATORS.map((s) => s.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.length).toBeGreaterThanOrEqual(45);
  });

  it("zips a re-parametrised MACD and gives RSI and MACD their panes", () => {
    const pt = (v: number) => [{ ts: "2026-11-11T00:00:00", value: v }];
    const bundle = {
      series: {
        "macd_8_21_5.macd": pt(1),
        "macd_8_21_5.signal": pt(0.5),
        "macd_8_21_5.histogram": pt(0.5),
        rsi_21: pt(40),
        "psar_0.02_0.2.sar": pt(9),
        "psar_0.02_0.2.direction": pt(1),
      },
      meta: {
        macd_8_21_5: { pane: "separate", label: "MACD" },
        rsi_21: { pane: "separate", label: "RSI" },
        "psar_0.02_0.2": { pane: "price", label: "Parabolic SAR" },
      },
    };
    const macd = macdSeries(bundle, "macd_8_21_5");
    expect(macd).toEqual([{ ts: "2026-11-11T00:00:00", macd: 1, signal: 0.5, histogram: 0.5 }]);
    const layers = chartLayers(
      bundle,
      ["rsi_21", "macd_8_21_5", "psar_0.02_0.2"],
      ["rsi_21", "macd_8_21_5"],
    );
    expect(layers.panes).toEqual([]);
    expect(Object.keys(layers.overlays)).toEqual(["psar_0.02_0.2.sar"]);
    const panes = allPanes({
      overlays: layers.overlays,
      rsi: bundle.series.rsi_21,
      rsiKey: "rsi_21",
      macd,
      macdKey: "macd_8_21_5",
    });
    expect(panes.map((p) => [p.kind, p.label])).toEqual([
      ["price", "Price"],
      ["volume", "Volume"],
      ["rsi", "RSI 21"],
      ["macd", "MACD 8, 21, 5"],
    ]);
    const sar = panes[0].series.find((s) => s.kind === "line");
    expect(sar).toMatchObject({ key: "psar_0.02_0.2.sar", dots: true });
  });
});

describe("evidence badges (A3.4)", () => {
  it("states the grade, sample, horizon, universe and association", () => {
    const badge = indicatorBadge(RSI, "rsi_14");
    expect(badge).toMatchObject({ text: "C", graded: true });
    expect(badge.title).toContain("Grade C");
    expect(badge.title).toContain("RSI(14) crosses up through 30");
    expect(badge.title).toContain("412 events over 25 symbols");
    expect(badge.title).toContain("20 sessions after each");
    expect(badge.title).toContain("survivorship-biased");
    expect(badge.title).toContain("Association, not cause");
    expect(badge.title).not.toContain("not on the");
  });

  it("says a re-parametrised study shows the default's grade", () => {
    expect(indicatorBadge(RSI, "rsi_21").title).toContain(
      "Graded on rsi_14, not on the rsi_21 drawn",
    );
  });

  it("never makes a grade up", () => {
    expect(indicatorBadge(BB)).toMatchObject({ text: "No grade", graded: false });
    expect(indicatorBadge(undefined).text).toBe("No grade");
    const ungraded = { ...RSI, signal: { ...RSI_SIGNAL, evidence: null } };
    expect(indicatorBadge(ungraded)).toMatchObject({ text: "Not graded", graded: false });
    const few = {
      ...RSI,
      signal: { ...RSI_SIGNAL, evidence: { ...EVIDENCE, grade: "insufficient" as const } },
    };
    expect(indicatorBadge(few)).toMatchObject({ text: "Too few", graded: false });
    expect(badgesFor(["rsi_21", "bb_20_2"], CATALOG)).toMatchObject({
      rsi_21: { text: "C" },
      bb_20_2: { text: "No grade" },
    });
    expect(badgesFor(["rsi_21"], null)).toEqual({});
  });

  it("shows the badge beside the study in the legend", () => {
    const bars = [
      { ts: "2026-11-10T00:00:00", open: "1", high: "2", low: "1", close: "2", volume: 10 },
      { ts: "2026-11-11T00:00:00", open: "2", high: "3", low: "1", close: "2.5", volume: 10 },
    ];
    render(
      <PriceChart
        bars={bars}
        rsi={[{ ts: "2026-11-11T00:00:00", value: 44 }]}
        rsiKey="rsi_21"
        overlays={{ "psar_0.02_0.2.sar": [{ ts: "2026-11-11T00:00:00", value: 1.5 }] }}
        badges={badgesFor(["rsi_21", "psar_0.02_0.2"], CATALOG)}
      />,
    );
    const legend = screen.getByTestId("chart-legend-indicators");
    const badges = within(legend).getAllByTestId("legend-badge");
    expect(badges.map((b) => b.textContent?.split(" ").slice(0, 2).join(" "))).toEqual([
      "No grade",
      "Grade C",
    ]);
    expect(badges[1]).toHaveAttribute("title", expect.stringContaining("not on the rsi_21 drawn"));
    expect(within(legend).getByText("RSI 21")).toBeInTheDocument();
    // Parabolic SAR draws as dots.
    const sar = lwcCalls.series.find((s) => s.options.pointMarkersVisible);
    expect(sar?.options).toMatchObject({ lineVisible: false, pointMarkersVisible: true });
  });
});

describe("the parameter editor (A3.4)", () => {
  it("applies an edited parameter with Enter and refuses one out of bounds", () => {
    const onApply = vi.fn();
    render(<StudyEditor item={BB} studyKey="bb_20_2" onApply={onApply} onRemove={() => {}} />);
    const k = screen.getByRole("spinbutton", { name: "Bollinger Bands 20, 2 k" });
    expect(k).toHaveAttribute("max", "10");
    expect(k).toHaveAttribute("step", "0.1");
    fireEvent.change(k, { target: { value: "11" } });
    expect(k).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("k must be above 0 and at most 10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    fireEvent.submit(k.closest("form") as HTMLFormElement);
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.change(k, { target: { value: "2.5" } });
    fireEvent.submit(k.closest("form") as HTMLFormElement);
    expect(onApply).toHaveBeenCalledWith("bb_20_2.5");
  });

  it("resets to the defaults and removes", () => {
    const onApply = vi.fn();
    const onRemove = vi.fn();
    render(<StudyEditor item={RSI} studyKey="rsi_21" onApply={onApply} onRemove={onRemove} />);
    expect(screen.getByRole("spinbutton", { name: "RSI 21 n" })).toHaveValue(21);
    fireEvent.click(screen.getByRole("button", { name: "Reset RSI 21 to defaults" }));
    expect(onApply).toHaveBeenCalledWith("rsi_14");
    fireEvent.click(screen.getByRole("button", { name: "Remove RSI 21" }));
    expect(onRemove).toHaveBeenCalled();
    expect(screen.getByTestId("evidence-badge")).toHaveTextContent("Grade C");
  });

  it("offers a choice as a select", () => {
    const onApply = vi.fn();
    render(<StudyEditor item={PIVOTS} studyKey="pivots_3" onApply={onApply} onRemove={() => {}} />);
    const basis = screen.getByRole("combobox", { name: "Pivot points (classic) 3 basis" });
    expect(basis).toHaveValue("3");
    fireEvent.change(basis, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApply).toHaveBeenCalledWith("pivots_2");
  });

  it("adds a study at its defaults and edits the URL key from the menu", () => {
    const onChange = vi.fn();
    render(<IndicatorMenu indicators={["rsi_14"]} catalog={CATALOG} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Indicators, 1 selected" }));
    const menu = screen.getByTestId("indicator-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "Add Parabolic SAR" }));
    expect(onChange).toHaveBeenLastCalledWith(["rsi_14", "psar_0.02_0.2"]);
    expect(within(menu).getByRole("button", { name: "RSI (added)" })).toBeDisabled();
    fireEvent.change(within(menu).getByRole("spinbutton", { name: "RSI 14 n" }), {
      target: { value: "21" },
    });
    fireEvent.click(within(menu).getByRole("button", { name: "Apply" }));
    expect(onChange).toHaveBeenLastCalledWith(["rsi_21"]);
    fireEvent.change(within(menu).getByRole("searchbox", { name: "Filter studies" }), {
      target: { value: "boll" },
    });
    expect(
      within(menu)
        .getAllByTestId("add-study")
        .map((b) => b.dataset.study),
    ).toEqual(["bb"]);
  });

  it("writes the edited key into the stock page URL", () => {
    render(
      <StockChartToolbar ticker="AAPL" timeframe="1Y" indicators={["rsi_14"]} catalog={CATALOG} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Indicators, 1 selected" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "RSI 14 n" }), {
      target: { value: "21" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(push).toHaveBeenCalledWith("/stocks/AAPL?tf=1Y&indicators=rsi_21");
  });
});

describe("series keys with decimal parameters (A3.4)", () => {
  it("never splits on a parameter's dot", async () => {
    const { splitSeriesKey } = await import("@/lib/stock-workspace");
    expect(splitSeriesKey("bb_20_2.5.upper")).toEqual(["bb_20_2.5", "upper"]);
    expect(splitSeriesKey("psar_0.02_0.2")).toEqual(["psar_0.02_0.2", undefined]);
    expect(splitSeriesKey("rsi_14")).toEqual(["rsi_14", undefined]);
    const pt = [{ ts: "2026-11-11T00:00:00", value: 1 }];
    const bundle = {
      series: { "bb_20_2.upper": pt, "bb_20_2.5.upper": pt },
      meta: {
        bb_20_2: { pane: "price", label: "BB" },
        "bb_20_2.5": { pane: "price", label: "BB" },
      },
    };
    expect(Object.keys(chartLayers(bundle, ["bb_20_2"]).overlays)).toEqual(["bb_20_2.upper"]);
  });
});

describe("the legend groups a study's outputs (A3.4)", () => {
  it("names a multi-output study once", () => {
    const groups = groupLegend([
      { key: "ichimoku_9_26_52_26.tenkan", label: "x", value: "1" },
      { key: "ichimoku_9_26_52_26.senkou_a", label: "x", value: "2" },
      { key: "bb_20_2.5.upper", label: "x", value: "3" },
      { key: "rsi_21", label: "RSI 21", value: "4" },
    ]);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.short)])).toEqual([
      ["Ichimoku Cloud 9, 26, 52, 26", ["tenkan", "span A"]],
      ["Bollinger Bands 20, 2.5", ["upper"]],
      ["RSI 21", [""]],
    ]);
  });
});
