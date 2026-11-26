import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";
import { RegimePopover } from "@/components/regime-popover";
import { RelativeStrengthStrip, ordinal } from "@/components/relative-strength-strip";
import { EventToggles } from "@/components/stock-chart-toolbar";
import { barTimeToUtcSeconds } from "@/lib/api-time";
import type { MarketRegime, RelativeStrength } from "@/lib/api/chart-context";
import {
  type ChartEvent,
  eventBarIndex,
  eventsByBar,
  legendEvents,
  mergeEvents,
  parseEventsParam,
  resolveEventTypes,
  splitLabel,
  toggleEventsParam,
} from "@/lib/chart-events";
import { parseChartView } from "@/lib/chart-view";
import { buildStockChartHref } from "@/lib/stock-workspace";

import { clickAt, hover, lwcCalls, resetLwc } from "../stubs/lightweight-charts";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const bar = (ts: string, c: number) => ({
  ts,
  open: String(c),
  high: String(c + 1),
  low: String(c - 1),
  close: String(c),
  volume: 1000,
});
// Thu 6, Fri 7, Mon 10, Tue 11 Nov 2025.
const BARS = [
  bar("2025-11-06T00:00:00", 10),
  bar("2025-11-07T00:00:00", 11),
  bar("2025-11-10T00:00:00", 12),
  bar("2025-11-11T00:00:00", 13),
];

const NEWS: ChartEvent = {
  type: "news",
  date: "2025-11-08", // a Saturday
  count: 2,
  sources: ["AP", "Reuters"],
  headlines: [
    {
      id: "d1",
      title: "Apple headline",
      source: "Reuters",
      url: "https://news.example.test/d1",
      available_at: "2025-11-08T10:00:00",
      published_at: null,
    },
    {
      id: "d2",
      title: "Second headline",
      source: "AP",
      url: null,
      available_at: "2025-11-08T12:00:00",
      published_at: null,
    },
  ],
};
const EARNINGS: ChartEvent = {
  type: "earnings",
  date: "2025-11-06",
  fiscal_period: "Q4",
  report_time: "AMC",
  eps_actual: "1.64",
  eps_estimate: "1.60",
  surprise_pct: null,
};
const SPLIT: ChartEvent = { type: "split", date: "2025-11-07", ratio_from: "1", ratio_to: "4" };
const DIVIDEND: ChartEvent = {
  type: "dividend",
  date: "2025-11-10",
  amount: "0.26",
  currency: "USD",
};
const FILL: ChartEvent = {
  type: "fill",
  date: "2025-11-11",
  ts: "2025-11-11T21:00:00",
  side: "buy",
  quantity: "5",
  price: "13",
  r_multiple: null,
};

beforeEach(() => {
  resetLwc();
  window.localStorage.clear();
});

describe("event URL state (A3.5)", () => {
  it("defaults to the public types, adding fills when signed in", () => {
    expect(resolveEventTypes(undefined, false)).toEqual(["news", "earnings", "dividend", "split"]);
    expect(resolveEventTypes(undefined, true)).toEqual([
      "news",
      "earnings",
      "dividend",
      "split",
      "fill",
    ]);
    // Fills never show signed out, even if the URL asks.
    expect(resolveEventTypes("news,fill", false)).toEqual(["news"]);
    expect(resolveEventTypes("", true)).toEqual([]);
  });

  it("normalises ?events= and leaves the default out of links", () => {
    expect(parseEventsParam("split, NEWS,bogus")).toBe("news,split");
    expect(parseEventsParam(undefined)).toBeUndefined();
    expect(parseChartView({ events: "fill,news" }).events).toBe("news,fill");
    expect(parseChartView({}).events).toBeUndefined();
    expect(toggleEventsParam(undefined, "news", false)).toBe("earnings,dividend,split");
    expect(toggleEventsParam("earnings,dividend,split", "news", false)).toBeUndefined();
    expect(toggleEventsParam(undefined, "fill", true)).toBe("news,earnings,dividend,split");
    const view = { ...parseChartView({}), events: "news" };
    expect(buildStockChartHref("AAPL", "1Y", [], "1d", view)).toBe(
      "/stocks/AAPL?tf=1Y&indicators=&events=news",
    );
  });

  it("renders one switch per type with its state and the next URL", () => {
    render(
      <EventToggles
        hrefFor={(events) => (events === undefined ? "/x" : `/x?events=${events}`)}
        param="news,split"
        signedIn={false}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Chart events" });
    const switches = within(nav).getAllByRole("switch");
    expect(switches.map((s) => s.getAttribute("data-event-type"))).toEqual([
      "news",
      "earnings",
      "dividend",
      "split",
    ]);
    const news = within(nav).getByRole("switch", { name: "Hide news on the chart" });
    expect(news).toHaveAttribute("aria-checked", "true");
    expect(news).toHaveAttribute("href", "/x?events=split");
    const earnings = within(nav).getByRole("switch", { name: "Show earnings on the chart" });
    expect(earnings).toHaveAttribute("aria-checked", "false");
    expect(earnings).toHaveAttribute("href", "/x?events=news,earnings,split");
  });
});

describe("placing events on bars (A3.5)", () => {
  const dates = BARS.map((b) => b.ts.slice(0, 10));

  it("daily: its own bar, else the next one, none after the last", () => {
    expect(eventBarIndex("2025-11-07", "1d", dates)).toBe(1);
    expect(eventBarIndex("2025-11-08", "1d", dates)).toBe(2); // Saturday -> Monday
    expect(eventBarIndex("2025-11-01", "1d", dates)).toBe(0);
    expect(eventBarIndex("2025-11-12", "1d", dates)).toBeNull();
  });

  it("weekly and monthly: the bar whose period contains the date", () => {
    const weekly = ["2025-11-07", "2025-11-14"];
    expect(eventBarIndex("2025-11-08", "1wk", weekly)).toBe(0); // same ISO week
    expect(eventBarIndex("2025-11-10", "1wk", weekly)).toBe(1);
    expect(eventBarIndex("2025-10-31", "1wk", weekly)).toBeNull();
    expect(eventBarIndex("2025-11-03", "1mo", ["2025-10-31", "2025-11-28"])).toBe(1);
  });

  it("groups, merges, filters and words events", () => {
    const merged = mergeEvents(
      [
        [NEWS, SPLIT],
        [FILL, EARNINGS],
      ],
      ["news", "split", "earnings"],
    );
    expect(merged.map((e) => e.type)).toEqual(["earnings", "split", "news"]);
    const byBar = eventsByBar(
      [NEWS, DIVIDEND],
      "1d",
      BARS.map((b) => b.ts),
    );
    expect(byBar.get(2)?.map((e) => e.type)).toEqual(["news", "dividend"]);
    expect(legendEvents(byBar.get(2) ?? [])).toBe("2 news, ex-dividend");
    expect(splitLabel(SPLIT as Extract<ChartEvent, { type: "split" }>)).toBe("4-for-1 split");
  });
});

describe("markers on the price chart (A3.5)", () => {
  it("draws one marker per type per bar, with news counts and fill arrows", () => {
    render(<PriceChart bars={BARS} events={[EARNINGS, SPLIT, NEWS, DIVIDEND, FILL]} />);
    const markers = lwcCalls.markers.at(-1) as { id: string; text: string; time: number }[];
    expect(markers.map((m) => m.id)).toEqual([
      "event:0:earnings",
      "event:1:split",
      "event:2:news",
      "event:2:dividend",
      "event:3:fill:2025-11-11T21:00:00",
    ]);
    expect(markers.find((m) => m.id === "event:2:news")?.text).toBe("2");
    expect(markers.at(-1)?.text).toBe("B");
  });

  it("notes the hovered bar's events in the legend and opens the headlines on click", () => {
    render(<PriceChart bars={BARS} events={[NEWS, DIVIDEND]} currency="USD" />);
    act(() => hover(barTimeToUtcSeconds("2025-11-10T00:00:00")));
    expect(screen.getByTestId("legend-events")).toHaveTextContent("Events: 2 news, ex-dividend");
    act(() => clickAt(barTimeToUtcSeconds("2025-11-10T00:00:00")));
    const popover = screen.getByTestId("event-popover");
    expect(popover).toHaveAttribute("role", "dialog");
    const link = within(popover).getByRole("link", { name: "Apple headline" });
    expect(link).toHaveAttribute("href", "https://news.example.test/d1");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(popover).getByText("Second headline")).toBeInTheDocument();
    expect(popover).toHaveTextContent("Ex-dividend 0.26 USD");
    fireEvent.keyDown(popover, { key: "Escape" });
    expect(screen.queryByTestId("event-popover")).toBeNull();
    // A click on a bar without events opens nothing.
    act(() => clickAt(barTimeToUtcSeconds("2025-11-06T00:00:00")));
    expect(screen.queryByTestId("event-popover")).toBeNull();
  });

  it("opens the same list with Enter on a bar from the keyboard", () => {
    render(<PriceChart bars={BARS} events={[NEWS]} />);
    const chart = screen.getByTestId("price-chart");
    fireEvent.keyDown(chart, { key: "ArrowLeft" }); // last bar -> index 2
    fireEvent.keyDown(chart, { key: "Enter" });
    expect(screen.getByTestId("event-popover")).toHaveTextContent("2 news items (AP, Reuters)");
  });

  it("lists every event under the chart, newest first", () => {
    render(<PriceChart bars={BARS} events={[EARNINGS, NEWS, FILL]} />);
    const list = screen.getByTestId("chart-events");
    expect(within(list).getByText("Chart events (3)")).toBeInTheDocument();
    expect(
      within(list)
        .getAllByTestId("event-item")
        .map((li) => li.dataset.type),
    ).toEqual(["fill", "news", "earnings"]);
    expect(list).toHaveTextContent("Bought 5 at 13");
    expect(list).toHaveTextContent("Earnings (Q4, AMC); EPS 1.64 vs 1.6 estimated");
  });

  it("says when no event of the shown types falls in the range", () => {
    render(<PriceChart bars={BARS} events={[]} />);
    expect(screen.getByTestId("chart-events")).toHaveTextContent(
      "No events of the shown types in this range.",
    );
  });

  it("draws a delivery pane with its average and its own legend labels", () => {
    render(
      <PriceChart
        bars={BARS}
        panes={[
          {
            name: "delivery",
            label: "Delivery %",
            lines: {
              delivery: [{ ts: "2025-11-11T00:00:00", value: 55 }],
              "delivery.avg_20": [{ ts: "2025-11-11T00:00:00", value: 48.5 }],
            },
            outputLabels: { delivery: "Delivery %", "delivery.avg_20": "20-day avg" },
          },
        ]}
      />,
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute(
      "data-panes",
      "price,volume,delivery",
    );
    expect(screen.getByTestId("chart-legend-indicators")).toHaveTextContent("20-day avg 48.5");
  });
});

describe("relative strength strip (A3.5)", () => {
  const rs: RelativeStrength = {
    ticker: "AAPL",
    market: "US",
    benchmark: "^GSPC",
    benchmark_name: "S&P 500",
    as_of: "2025-04-07",
    method: "…",
    periods: [
      { period: "1m", sessions: 21, return_pct: -24.1, percentile: 4.2 },
      { period: "3m", sessions: 63, return_pct: -25.4, percentile: 12.5 },
      { period: "6m", sessions: 126, return_pct: null, percentile: null },
      { period: "12m", sessions: 252, return_pct: 7.5, percentile: 62.5 },
    ],
    universe: {
      market: "US",
      size: 25,
      as_of: "2025-04-07",
      point_in_time: false,
      survivorship_biased: true,
      note: "Current symbol list, not point in time: survivorship-biased.",
    },
    high_52w: 260.1,
    last_close: 181.46,
    distance_from_high_52w_pct: -30.23,
    reason: null,
  };

  it("shows each percentile, the 52-week distance and the universe stamp", () => {
    render(<RelativeStrengthStrip strength={rs} />);
    const strip = screen.getByTestId("relative-strength");
    expect(strip).toHaveTextContent("RS rank 1M4th");
    expect(strip).toHaveTextContent("RS rank 12M63rd");
    expect(strip).toHaveTextContent("From 52-week high−30.2%");
    expect(screen.getByTestId("rs-universe")).toHaveTextContent(
      "Percentile of the return among 25 US symbols on Apr 7, 2025",
    );
    expect(screen.getByTestId("rs-universe")).toHaveTextContent("survivorship-biased");
    expect([1, 2, 3, 11, 12, 13, 21, 100].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "11th",
      "12th",
      "13th",
      "21st",
      "100th",
    ]);
  });
});

describe("regime badge (A3.5)", () => {
  const market: MarketRegime = {
    market: "US",
    name: "US",
    index: "^GSPC",
    index_name: "S&P 500",
    as_of: "2025-04-07",
    state: "High-vol down",
    reason: null,
    breadth_count: 3,
    breadth_universe: 25,
    breadth_as_of: "2025-04-07",
    vol_window_sessions: 1260,
    hv_20: 38.2,
    inputs: [
      { name: "index_close", value: 5062.25, description: "The index's latest close." },
      { name: "index_sma_200", value: 5750.1, description: "…" },
      { name: "breadth_200", value: 12, description: "…" },
      { name: "vol_pct_20", value: 97.5, description: "…" },
    ],
    rules: [
      {
        state: "High-vol down",
        rule: "index_close < index_sma_200 and vol_pct_20 >= 80",
        description: "…",
        met: true,
      },
      { state: "Calm trend", rule: "…", description: "…", met: false },
      { state: "Choppy", rule: "otherwise", description: "…", met: null },
    ],
  };

  it("names the state and opens the rules with their inputs", () => {
    render(
      <RegimePopover market={market} method="Rules read in order." disclaimer="Not advice." />,
    );
    const badge = screen.getByRole("button", { name: /US market regime: High-vol down/ });
    expect(badge).toHaveAttribute("data-state", "High-vol down");
    fireEvent.click(badge);
    const popover = screen.getByTestId("regime-popover-US");
    expect(popover).toHaveTextContent("S&P 500 (^GSPC), as of Apr 7, 2025");
    expect(within(popover).getAllByTestId("regime-rule")[0]).toHaveTextContent(
      "High-vol down (met)index_close < index_sma_200 and vol_pct_20 >= 80",
    );
    expect(screen.getByTestId("regime-input-breadth_200")).toHaveTextContent("12% (3 of 25)");
    expect(screen.getByTestId("regime-input-vol_pct_20")).toHaveTextContent("97.5th pct");
    expect(popover).toHaveTextContent("Not advice.");
    expect(popover.textContent?.toLowerCase()).not.toMatch(/\b(buy|sell)\b/);
  });

  it("says unknown without data", () => {
    render(
      <RegimePopover
        market={{ ...market, state: null, reason: "Not enough data: index_close unknown." }}
        method="m"
        disclaimer="d"
      />,
    );
    expect(screen.getByRole("button", { name: /US market regime: Unknown/ })).toHaveAttribute(
      "data-state",
      "unknown",
    );
  });
});
