import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";
import { StockChartToolbar } from "@/components/stock-chart-toolbar";
import { eventBarIndex } from "@/lib/chart-events";
import { legendAt } from "@/lib/chart-legend";
import { anchorBar, sessionDateOf } from "@/lib/drawings/anchor";
import { avwapShapes } from "@/lib/drawings/scene";
import { sessionStarts } from "@/lib/session-breaks";
import {
  buildStockChartHref,
  clipBundleFrom,
  formatBarTime,
  intradayBarsForLookback,
  intradayLookbacks,
  isIntradayInterval,
  lastSessions,
  parseIntradayLookback,
  parseStockInterval,
  partialBarLabel,
  sessionsForLookback,
  sourceBadgeLabel,
} from "@/lib/stock-workspace";

import { lwcCalls, resetLwc } from "../stubs/lightweight-charts";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

beforeEach(() => resetLwc());

/** A 15-minute NSE bar opening at `ts` (naive UTC) in session `day`. */
const bar = (ts: string, day: string, close = "100", extra: Record<string, unknown> = {}) => ({
  ts,
  open: close,
  high: close,
  low: close,
  close,
  volume: 10,
  session_date: day,
  feed: "file",
  badge: "File (local)",
  partial: false,
  ...extra,
});

// 09:15 and 15:15 IST on 30 Jan 2026, then 09:15 IST on 2 Feb 2026 (UTC +5:30).
const BARS = [
  bar("2026-01-30T03:45:00", "2026-01-30"),
  bar("2026-01-30T09:45:00", "2026-01-30", "101"),
  bar("2026-02-02T03:45:00", "2026-02-02", "102"),
];

describe("intraday intervals (A6.2)", () => {
  it("parses intraday values and keeps daily as the default", () => {
    expect(parseStockInterval("15m")).toBe("15m");
    expect(parseStockInterval("60m")).toBe("60m");
    expect(parseStockInterval("2m")).toBe("1d");
    expect(isIntradayInterval("1m")).toBe(true);
    expect(isIntradayInterval("1mo")).toBe(false);
  });

  it("maps lookbacks to bar counts per session and caps them at 5,000", () => {
    // One session of headroom; the page keeps the newest whole sessions.
    expect(intradayBarsForLookback("1D", "1m", true)).toBe(2 * 375);
    expect(intradayBarsForLookback("1D", "1m", false)).toBe(2 * 390);
    expect(intradayBarsForLookback("5D", "5m", true)).toBe(6 * 75);
    expect(intradayBarsForLookback("1M", "60m", true)).toBe(23 * 7);
    expect(intradayBarsForLookback("1M", "30m", true)).toBe(23 * 13);
    expect(intradayBarsForLookback("1Y", "60m", true)).toBe(253 * 7);
    expect(intradayBarsForLookback("5D", "1m", false)).toBe(6 * 390);
    expect(intradayLookbacks("1m")).toEqual(["1D", "5D"]);
    // A daily lookback in the URL falls back to the interval's default.
    expect(parseIntradayLookback("1Y", "1m")).toBe("1D");
    expect(parseIntradayLookback("3M", "15m")).toBe("3M");
    expect(parseIntradayLookback(undefined, "60m")).toBe("1M");
  });

  it("writes intraday intervals in the chart link", () => {
    expect(buildStockChartHref("TCS.NS", "5D", [], "15m")).toBe(
      "/stocks/TCS.NS?tf=5D&indicators=&interval=15m",
    );
  });
});

describe("whole sessions", () => {
  it("keeps the newest sessions, a short Muhurat evening as one", () => {
    const bars = [
      bar("2024-10-31T09:45:00", "2024-10-31"),
      bar("2024-11-01T12:30:00", "2024-11-01"),
      bar("2024-11-01T12:45:00", "2024-11-01"),
    ];
    expect(lastSessions(bars, 1).map((b) => b.ts)).toEqual([
      "2024-11-01T12:30:00",
      "2024-11-01T12:45:00",
    ]);
    expect(lastSessions(bars, 5)).toHaveLength(3);
    expect(sessionsForLookback("5D")).toBe(5);
  });

  it("clips indicator points before the first bar drawn", () => {
    const bundle = {
      series: {
        rsi_14: [
          { ts: "2024-10-31T09:45:00", value: 1 },
          { ts: "2024-11-01T12:30:00", value: 2 },
        ],
      },
      macd: null,
    };
    expect(clipBundleFrom(bundle, "2024-11-01T12:30:00").series.rsi_14).toEqual([
      { ts: "2024-11-01T12:30:00", value: 2 },
    ]);
  });
});

describe("times in the venue's zone", () => {
  it("formats a UTC bar time in IST with the date, whatever the browser's zone", () => {
    expect(formatBarTime("2026-01-30T03:45:00", "Asia/Kolkata")).toBe("Jan 30, 2026 09:15 IST");
    // 18:15 IST Muhurat open: 12:45 UTC.
    expect(formatBarTime("2024-11-01T12:30:00", "Asia/Kolkata")).toBe("Nov 1, 2024 18:00 IST");
    expect(formatBarTime("2025-11-24T14:30:00", "America/New_York")).toBe("Nov 24, 2025 09:30 ET");
    // A zone suffix on the API value is respected.
    expect(formatBarTime("2026-01-30T03:45:00Z", "Asia/Kolkata")).toBe("Jan 30, 2026 09:15 IST");
  });

  it("labels a partial intraday bar by its open time", () => {
    const last = { ts: "2026-01-30T09:45:00", partial: true };
    expect(partialBarLabel(last, "15m", "Asia/Kolkata")).toBe(
      "Latest 15-minute bar so far (partial), opened Jan 30, 2026 15:15 IST. It is not a closed bar.",
    );
    expect(partialBarLabel({ ...last, partial: false }, "15m", "Asia/Kolkata")).toBeNull();
  });

  it("the legend reads the bar's time on intraday charts", () => {
    const row = legendAt({ bars: BARS, indicators: [] }, 1, (ts) =>
      formatBarTime(ts, "Asia/Kolkata"),
    );
    expect(row?.date).toBe("Jan 30, 2026 15:15 IST");
  });
});

describe("source badge", () => {
  it("names each feed", () => {
    expect(sourceBadgeLabel("file")).toBe("File · local");
    expect(sourceBadgeLabel("iex")).toBe("IEX only");
    expect(sourceBadgeLabel("sip")).toBe("SIP");
    expect(sourceBadgeLabel(null)).toBeNull();
  });

  it("shows on an intraday chart with the time zone, and not on daily", () => {
    const { unmount } = render(
      <PriceChart interval="15m" bars={BARS} timeZone="Asia/Kolkata" sourceFeed="file" />,
    );
    const badge = screen.getByTestId("chart-source-badge");
    expect(badge.textContent).toBe("Source: File · local");
    expect(badge.getAttribute("data-feed")).toBe("file");
    expect(screen.getByTestId("chart-time-zone").textContent).toContain(
      "Times in IST (Asia/Kolkata)",
    );
    expect(screen.getByTestId("chart-legend").textContent).toContain("Feb 2, 2026 09:15 IST");
    unmount();
    render(<PriceChart interval="1d" bars={[bar("2026-01-30T00:00:00", "2026-01-30")]} />);
    expect(screen.queryByTestId("chart-source")).toBeNull();
  });

  it("formats the time axis in the venue's zone and marks session breaks", () => {
    render(<PriceChart interval="15m" bars={BARS} timeZone="Asia/Kolkata" sourceFeed="file" />);
    const options = lwcCalls.chartOptions.at(-1) as {
      timeScale: { timeVisible: boolean; tickMarkFormatter: (t: number, k: number) => string };
      localization: { timeFormatter: (t: number) => string };
    };
    expect(options.timeScale.timeVisible).toBe(true);
    const t = Date.UTC(2026, 0, 30, 9, 45) / 1000;
    expect(options.timeScale.tickMarkFormatter(t, 3)).toBe("15:15");
    expect(options.timeScale.tickMarkFormatter(t, 2)).toBe("Jan 30");
    expect(options.localization.timeFormatter(t)).toBe("Jan 30, 2026 15:15 IST");
    // One break, before the 2 Feb session's first bar.
    expect(sessionStarts(BARS.map(sessionDateOf))).toEqual([2]);
    expect(lwcCalls.primitives.some((p) => p?.constructor?.name === "SessionBreaksPrimitive")).toBe(
      true,
    );
  });
});

describe("interval control visibility", () => {
  it("hides the intraday intervals when the symbol has none", () => {
    render(<StockChartToolbar ticker="AAPL" timeframe="1Y" indicators={[]} interval="1d" />);
    expect(screen.queryByTestId("intraday-intervals")).toBeNull();
    expect(screen.getByRole("navigation", { name: "Chart timeframe" }).textContent).toContain("5Y");
  });

  it("offers the symbol's intraday intervals with their lookbacks", () => {
    render(
      <StockChartToolbar
        ticker="TCS.NS"
        timeframe="1D"
        indicators={[]}
        interval="1m"
        intradayIntervals={["1m", "5m", "15m", "30m", "60m"]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Intraday interval" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["1m", "5m", "15m", "30m", "1h"]);
    expect(within(nav).getByRole("link", { name: "1-hour bars" }).getAttribute("href")).toBe(
      "/stocks/TCS.NS?tf=1M&indicators=&interval=60m",
    );
    expect(
      within(nav).getByRole("link", { name: "1-minute bars" }).getAttribute("aria-current"),
    ).toBe("page");
    // Lookbacks follow the interval: 1D and 5D on 1 minute.
    const tf = screen.getByRole("navigation", { name: "Chart timeframe" });
    expect(
      within(tf)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["1D", "5D"]);
    // Back to daily drops the intraday lookback.
    const daily = screen.getByRole("link", { name: "Daily bars" }).getAttribute("href");
    expect(daily).toBe("/stocks/TCS.NS?tf=1Y&indicators=");
  });

  it("shows only an hourly-only symbol's 1h", () => {
    render(
      <StockChartToolbar
        ticker="X.NS"
        timeframe="1Y"
        indicators={[]}
        interval="1d"
        intradayIntervals={["60m"]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Intraday interval" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["1h"]);
  });
});

describe("drawings and events on intraday bars", () => {
  const dates = ["2026-01-29", "2026-01-29", "2026-01-30", "2026-01-30", "2026-01-30"];

  it("a date anchor maps to its session's first bar", () => {
    expect(anchorBar("2026-01-30", "15m", dates)).toEqual({ index: 2, date: "2026-01-30" });
    expect(anchorBar("2026-01-31", "15m", dates)).toBeNull();
    // Daily keeps its rule.
    expect(anchorBar("2026-01-30", "1d", ["2026-01-29", "2026-01-30"])?.index).toBe(1);
  });

  it("an event lands on its session's first bar, a weekend one on the next session", () => {
    expect(eventBarIndex("2026-01-30", "5m", dates)).toBe(2);
    expect(eventBarIndex("2026-01-28", "5m", dates)).toBe(0);
    expect(eventBarIndex("2026-02-01", "5m", dates)).toBeNull();
  });

  it("an intraday AVWAP point sits on its own bar, not its date", () => {
    const ctx = {
      interval: "15m" as const,
      barDates: dates,
      xOfLogical: (l: number) => l * 10,
      yOfPrice: (p: number) => 200 - p,
      width: 400,
      height: 200,
      colours: {
        drawing: { aqua: "#0ff" } as never,
        positive: "#0f0",
        negative: "#f00",
        text: "#fff",
        labelBg: "#000",
      },
    };
    const shapes = avwapShapes(
      {
        id: "1",
        kind: "avwap",
        points: [{ ts: "2026-01-30", price: "" }],
        style: { colour: "aqua", width: 1, dash: "solid", fill_opacity: 0, bands: 0 },
        label: "a",
        avwap: [
          { date: "2026-01-30", vwap: 100, index: 2 },
          { date: "2026-01-30", vwap: 101, index: 3 },
          { date: "2026-01-30", vwap: 102, index: 4 },
        ],
      },
      ctx,
      false,
    );
    const path = shapes.find((s) => s.type === "path") as { points: [number, number][] };
    expect(path.points).toEqual([
      [20, 100],
      [30, 99],
      [40, 98],
    ]);
  });
});
