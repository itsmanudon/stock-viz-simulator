import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";
import { StockChartToolbar } from "@/components/stock-chart-toolbar";
import { barTimeToUtcSeconds } from "@/lib/api-time";
import { buildLegendModel, formatIndicatorValue, legendAt, legendText } from "@/lib/chart-legend";
import {
  DEFAULT_PANE_HEIGHTS,
  allPanes,
  assemblePanes,
  overlayLabel,
  paneHeight,
  readPaneLayout,
  writePaneLayout,
} from "@/lib/chart-panes";
import { DEFAULT_CHART_VIEW, parseChartView } from "@/lib/chart-view";
import { heikinAshi } from "@/lib/heikin-ashi";
import { buildStockChartHref } from "@/lib/stock-workspace";

import { hover, lwcCalls, resetLwc } from "../stubs/lightweight-charts";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const bar = (ts: string, o: number, h: number, l: number, c: number, volume = 1000) => ({
  ts,
  open: String(o),
  high: String(h),
  low: String(l),
  close: String(c),
  volume,
});
const BARS = [
  bar("2026-11-09T00:00:00", 10, 12, 9, 11, 1500),
  bar("2026-11-10T00:00:00", 11, 13, 10, 12, 2_500_000),
  bar("2026-11-11T00:00:00", 12, 12.5, 8, 9, 900),
];
const point = (ts: string, value: number) => ({ ts, value });
const RSI = [point("2026-11-10T00:00:00", 55), point("2026-11-11T00:00:00", 41.256)];
const MACD = [
  { ts: "2026-11-10T00:00:00", macd: 0.5, signal: 0.25, histogram: 0.25 },
  { ts: "2026-11-11T00:00:00", macd: -0.2, signal: 0.1, histogram: -0.3 },
];
const SMA = { sma_50: [point("2026-11-11T00:00:00", 10.5)] };
const ADX = {
  name: "adx_14",
  label: "ADX 14",
  lines: { "adx_14.adx": [point("2026-11-11T00:00:00", 22)] },
};

beforeEach(() => {
  resetLwc();
  push.mockReset();
  window.localStorage.clear();
});

describe("pane assembly (A3.1)", () => {
  it("puts each series on its pane in a fixed order", () => {
    const panes = allPanes({ overlays: SMA, rsi: RSI, macd: MACD, panes: [ADX] });
    expect(panes.map((p) => p.kind)).toEqual(["price", "volume", "rsi", "macd", "adx_14"]);
    expect(panes[0].series.map((s) => s.kind)).toEqual(["price", "line"]);
    expect(panes[1].series).toEqual([{ kind: "volume" }]);
    expect(panes[2].guides).toEqual([70, 30]);
    expect(panes[3].series.map((s) => s.kind)).toEqual(["line", "line", "histogram"]);
    expect(panes[4].series.map((s) => (s.kind === "line" ? s.label : s.kind))).toEqual([
      "ADX 14 adx",
    ]);
  });

  it("drops empty overlays, volume when asked, and collapsed panes but never price", () => {
    const panes = allPanes({ overlays: { sma_20: [] }, showVolume: false });
    expect(panes.map((p) => p.kind)).toEqual(["price"]);
    expect(panes[0].series).toHaveLength(1);

    const { visible, collapsed } = assemblePanes(
      { rsi: RSI, macd: MACD },
      new Set(["rsi", "price"]),
    );
    expect(visible.map((p) => p.kind)).toEqual(["price", "volume", "macd"]);
    expect(collapsed.map((p) => p.kind)).toEqual(["rsi"]);
  });

  it("names overlays by their menu label and output", () => {
    expect(overlayLabel("sma_50")).toBe("SMA 50");
    expect(overlayLabel("bb_20_2.upper")).toBe("Bollinger Bands 20, 2 upper");
    expect(overlayLabel("custom_9")).toBe("CUSTOM_9");
  });

  it("uses a stored height only when it is sane", () => {
    const [price] = allPanes({});
    expect(paneHeight(price, {})).toBe(DEFAULT_PANE_HEIGHTS.price);
    expect(paneHeight(price, { price: 412.4 })).toBe(412);
    expect(paneHeight(price, { price: 3 })).toBe(DEFAULT_PANE_HEIGHTS.price);
    expect(paneHeight(price, { price: Number.NaN })).toBe(DEFAULT_PANE_HEIGHTS.price);
  });

  it("remembers the layout in localStorage and survives bad or blocked storage", () => {
    writePaneLayout({ heights: { rsi: 150 }, collapsed: ["macd", "price"] });
    expect(readPaneLayout()).toEqual({ heights: { rsi: 150 }, collapsed: ["macd"] });
    window.localStorage.setItem("stockviz:chart-panes", "{not json");
    expect(readPaneLayout()).toEqual({ heights: {}, collapsed: [] });
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readPaneLayout()).toEqual({ heights: {}, collapsed: [] });
    spy.mockRestore();
  });
});

describe("Heikin-Ashi (derived)", () => {
  it("matches hand-computed candles", () => {
    const ha = heikinAshi([
      { time: 1, open: 10, high: 12, low: 9, close: 11 },
      { time: 2, open: 11, high: 13, low: 10, close: 12 },
      { time: 3, open: 12, high: 12.5, low: 8, close: 9 },
      { time: 4, open: 9, high: 9.5, low: 9, close: 9.2 },
    ]);
    const expected = [
      // close (10+12+9+11)/4 = 10.5; first open (10+11)/2 = 10.5
      { time: 1, open: 10.5, high: 12, low: 9, close: 10.5 },
      // open (10.5+10.5)/2; close (11+13+10+12)/4
      { time: 2, open: 10.5, high: 13, low: 10, close: 11.5 },
      // open (10.5+11.5)/2; close (12+12.5+8+9)/4
      { time: 3, open: 11, high: 12.5, low: 8, close: 10.375 },
      // open (11+10.375)/2 = 10.6875 sits above the bar's high, so it is the high
      { time: 4, open: 10.6875, high: 10.6875, low: 9, close: 9.175 },
    ];
    expect(ha).toHaveLength(4);
    ha.forEach((candle, i) => {
      expect(candle.time).toBe(expected[i].time);
      for (const key of ["open", "high", "low", "close"] as const) {
        expect(candle[key]).toBeCloseTo(expected[i][key], 10);
      }
    });
    expect(heikinAshi([])).toEqual([]);
  });
});

describe("crosshair legend", () => {
  const model = buildLegendModel(BARS, allPanes({ overlays: SMA, rsi: RSI }));

  it("reads the last bar with no bar hovered", () => {
    const row = legendAt(model, null);
    expect(row).toMatchObject({
      index: 2,
      isLast: true,
      date: "Nov 11, 2026",
      open: "12.00",
      high: "12.50",
      low: "8.00",
      close: "9.00",
      change: "−3.00",
      changePct: "−25%",
      direction: -1,
      volume: "900",
    });
    expect(row?.indicators).toEqual([
      { key: "sma_50", label: "SMA 50", value: "10.5" },
      { key: "rsi_14", label: "RSI 14", value: "41.26" },
    ]);
  });

  it("shows a dash for an indicator with no value on the bar", () => {
    const row = legendAt(model, 0);
    expect(row?.indicators.map((i) => i.value)).toEqual(["—", "—"]);
    expect(row?.change).toBe("—");
    expect(row?.direction).toBeNull();
    expect(legendAt(model, 1)?.volume).toBe("2.5M");
    expect(legendAt(model, 1)?.change).toBe("+1.00");
    expect(legendAt(model, 99)?.index).toBe(2);
    expect(formatIndicatorValue(undefined)).toBe("—");
    expect(formatIndicatorValue(Number.NaN)).toBe("—");
    expect(legendAt(buildLegendModel([], []), null)).toBeNull();
  });

  it("reads as one sentence for the live region", () => {
    const row = legendAt(model, 1);
    expect(row && legendText(row)).toBe(
      "Nov 10, 2026: open 11.00, high 13.00, low 10.00, close 12.00, change +1.00 (+9.09%), " +
        "volume 2.5M. SMA 50 —, RSI 14 55.",
    );
  });
});

describe("the one chart", () => {
  it("builds one chart with every pane and reads the last bar", () => {
    render(<PriceChart bars={BARS} overlays={SMA} rsi={RSI} macd={MACD} panes={[ADX]} />);
    expect(lwcCalls.charts).toBe(1);
    const chart = screen.getByTestId("price-chart");
    expect(chart).toHaveAttribute("data-pane-count", "5");
    expect(chart).toHaveAttribute("data-panes", "price,volume,rsi,macd,adx_14");
    expect(lwcCalls.series.map((s) => [s.type, s.pane])).toEqual([
      ["CandlestickSeries", 0],
      ["LineSeries", 0],
      ["HistogramSeries", 1],
      ["LineSeries", 2],
      ["LineSeries", 3],
      ["LineSeries", 3],
      ["HistogramSeries", 3],
      ["LineSeries", 4],
    ]);
    // Pane heights as stretch factors: the defaults, in pane order.
    expect(lwcCalls.stretch).toEqual([300, 80, 110, 130, 100]);
    const legend = screen.getByTestId("chart-legend");
    expect(legend).toHaveAttribute("data-last", "true");
    expect(legend).toHaveTextContent("Nov 11, 2026");
    expect(legend).toHaveTextContent("C 9.00");
  });

  it("follows the crosshair and falls back to the last bar", () => {
    render(<PriceChart bars={BARS} rsi={RSI} />);
    act(() => hover(barTimeToUtcSeconds(BARS[1].ts)));
    expect(screen.getByTestId("chart-legend")).toHaveAttribute("data-bar-index", "1");
    expect(screen.getByTestId("chart-legend")).toHaveTextContent("RSI 14 55");
    act(() => hover(undefined));
    expect(screen.getByTestId("chart-legend")).toHaveAttribute("data-bar-index", "2");
  });

  it("steps the crosshair with the keyboard and zooms with + / -", () => {
    render(<PriceChart bars={BARS} />);
    const chart = screen.getByTestId("price-chart");
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(lwcCalls.crosshair.at(-1)).toEqual({ price: 12, time: barTimeToUtcSeconds(BARS[1].ts) });
    expect(screen.getByTestId("chart-legend")).toHaveAttribute("data-bar-index", "1");
    fireEvent.keyDown(chart, { key: "Home" });
    expect(screen.getByTestId("chart-legend")).toHaveAttribute("data-bar-index", "0");
    const before = lwcCalls.visibleRanges.length;
    fireEvent.keyDown(chart, { key: "+" });
    fireEvent.keyDown(chart, { key: "-" });
    expect(lwcCalls.visibleRanges.length).toBe(before + 2);
    const [zoomIn, zoomOut] = lwcCalls.visibleRanges.slice(-2);
    expect(zoomIn.to - zoomIn.from).toBeLessThan(zoomOut.to - zoomOut.from);
    expect(screen.getByText(/left and right arrows move one bar/)).toBeInTheDocument();
  });

  it("collapses a pane out of the chart and shows it again", () => {
    render(<PriceChart bars={BARS} rsi={RSI} />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse the RSI 14 pane" }));
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-panes", "price,volume");
    expect(lwcCalls.charts).toBe(2);
    expect(readPaneLayout().collapsed).toEqual(["rsi"]);
    fireEvent.click(screen.getByRole("button", { name: "Show RSI 14" }));
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-panes", "price,volume,rsi");
  });

  it("draws each chart type and applies the scale", () => {
    const types = {
      candles: "CandlestickSeries",
      hollow: "CandlestickSeries",
      bars: "BarSeries",
      line: "LineSeries",
      area: "AreaSeries",
      "heikin-ashi": "CandlestickSeries",
    } as const;
    for (const [type, series] of Object.entries(types)) {
      resetLwc();
      const { unmount } = render(
        <PriceChart bars={BARS} chartType={type as keyof typeof types} scale="log" />,
      );
      const main = lwcCalls.series[0];
      expect(main.type).toBe(series);
      expect(main.scaleOptions).toEqual([{ mode: 1 }]);
      if (type === "hollow") expect(main.options.borderVisible).toBe(true);
      if (type === "heikin-ashi") {
        expect(main.data[0]).toMatchObject({ open: 10.5, close: 10.5 });
        expect(screen.getByTestId("chart-legend")).toHaveTextContent("HA candles derived");
        // The legend still reads the stored close.
        expect(screen.getByTestId("chart-legend")).toHaveTextContent("C 9.00");
      }
      if (type === "line") expect(main.data[2]).toEqual({ time: expect.any(Number), value: 9 });
      unmount();
    }
    resetLwc();
    render(<PriceChart bars={BARS} scale="percent" />);
    expect(lwcCalls.series[0].scaleOptions).toEqual([{ mode: 2 }]);
    expect(screen.getAllByRole("img")[0].getAttribute("aria-label")).toContain("Percent scale");
  });

  it("keeps replay markers on the price pane with no indicator panes", () => {
    render(
      <PriceChart
        bars={BARS}
        markers={[
          { time: BARS[1].ts, position: "belowBar", color: "#000", shape: "arrowUp", text: "BUY" },
        ]}
      />,
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-panes", "price,volume");
    expect(screen.getAllByRole("img")[0].getAttribute("aria-label")).toContain(
      "Trade markers: BUY on Nov 10, 2026",
    );
  });
});

describe("chart view in the URL", () => {
  it("parses with defaults and leaves defaults out of links", () => {
    expect(parseChartView({})).toEqual(DEFAULT_CHART_VIEW);
    expect(parseChartView({ type: "heikin-ashi", scale: "log", adjustment: "raw" })).toEqual({
      type: "heikin-ashi",
      scale: "log",
      adjustment: "raw",
    });
    expect(parseChartView({ type: "renko", scale: "x", adjustment: "dividends" })).toEqual(
      DEFAULT_CHART_VIEW,
    );
    expect(buildStockChartHref("AAPL", "1Y", ["sma_50"], "1d", DEFAULT_CHART_VIEW)).toBe(
      "/stocks/AAPL?tf=1Y&indicators=sma_50",
    );
    expect(
      buildStockChartHref("AAPL", "1Y", [], "1wk", {
        type: "line",
        scale: "percent",
        adjustment: "raw",
      }),
    ).toBe("/stocks/AAPL?tf=1Y&indicators=&interval=1wk&type=line&scale=percent&adjustment=raw");
  });

  it("offers type, scale and adjustment controls that keep the rest of the state", () => {
    const view = { ...DEFAULT_CHART_VIEW, type: "bars" as const };
    render(
      <StockChartToolbar
        ticker="AAPL"
        timeframe="5Y"
        indicators={["rsi_14"]}
        interval="1wk"
        view={view}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Chart type" });
    expect(select).toHaveValue("bars");
    expect(
      within(select).getByRole("option", { name: "Heikin-Ashi (derived)" }),
    ).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "area" } });
    expect(push).toHaveBeenCalledWith(
      "/stocks/AAPL?tf=5Y&indicators=rsi_14&interval=1wk&type=area",
    );

    const scales = screen.getByRole("navigation", { name: "Price scale" });
    expect(within(scales).getByRole("link", { name: "Linear scale" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(scales).getByRole("link", { name: "Logarithmic scale" })).toHaveAttribute(
      "href",
      "/stocks/AAPL?tf=5Y&indicators=rsi_14&interval=1wk&type=bars&scale=log",
    );
    // The lookback keeps the chart type.
    expect(
      within(screen.getByRole("navigation", { name: "Chart timeframe" })).getByRole("link", {
        name: "1Y",
      }),
    ).toHaveAttribute("href", "/stocks/AAPL?tf=1Y&indicators=rsi_14&interval=1wk&type=bars");

    // No raw prices stored: the toggle is disabled and says why.
    const raw = screen.getByTestId("raw-unavailable");
    expect(raw).toHaveAttribute("aria-disabled", "true");
    expect(raw).toHaveAttribute("title", "Only adjusted prices are stored for this symbol");
    expect(
      within(screen.getByRole("navigation", { name: "Price adjustment" })).queryByRole("link", {
        name: "Raw prices",
      }),
    ).toBeNull();
  });

  it("links to raw prices when they are stored", () => {
    render(<StockChartToolbar ticker="RELIANCE.NS" timeframe="1Y" indicators={[]} hasRaw />);
    expect(screen.getByRole("link", { name: "Raw prices" })).toHaveAttribute(
      "href",
      "/stocks/RELIANCE.NS?tf=1Y&indicators=&adjustment=raw",
    );
    expect(screen.getByRole("link", { name: "Adjusted prices" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
