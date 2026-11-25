import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";
import { StockChartToolbar } from "@/components/stock-chart-toolbar";
import { UniverseNote, universeSummary } from "@/components/universe-note";
import {
  barsForLookback,
  buildStockChartHref,
  parseStockInterval,
  partialBarLabel,
} from "@/lib/stock-workspace";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const bar = (ts: string, close: string, partial?: boolean) => ({
  ts,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
  sessions: 5,
  partial: partial ?? false,
});

describe("bar interval (A1.4a)", () => {
  it("parses the URL value, defaulting to daily", () => {
    expect(parseStockInterval(undefined)).toBe("1d");
    expect(parseStockInterval("1wk")).toBe("1wk");
    expect(parseStockInterval("1mo")).toBe("1mo");
    expect(parseStockInterval("1h")).toBe("1d");
  });

  it("keeps daily links unchanged and adds the interval otherwise", () => {
    expect(buildStockChartHref("AAPL", "1Y", ["sma_50"])).toBe(
      "/stocks/AAPL?tf=1Y&indicators=sma_50",
    );
    expect(buildStockChartHref("AAPL", "5Y", [], "1wk")).toBe(
      "/stocks/AAPL?tf=5Y&indicators=&interval=1wk",
    );
  });

  it("counts a lookback in bars of the interval", () => {
    expect(barsForLookback(252, "1d")).toBe(252);
    expect(barsForLookback(252, "1wk")).toBe(51);
    expect(barsForLookback(252, "1mo")).toBe(12);
    expect(barsForLookback(5000, "1wk")).toBe(1000);
  });

  it("renders a keyboard-reachable interval control that keeps the lookback", () => {
    render(<StockChartToolbar ticker="AAPL" timeframe="1Y" indicators={[]} interval="1wk" />);
    const nav = screen.getByRole("navigation", { name: "Bar interval" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("aria-label"))).toEqual([
      "Daily bars",
      "Weekly bars",
      "Monthly bars",
    ]);
    expect(within(nav).getByRole("link", { name: "Weekly bars" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Monthly bars" })).toHaveAttribute(
      "href",
      "/stocks/AAPL?tf=1Y&indicators=&interval=1mo",
    );
    // A lookback link keeps the weekly interval.
    const ranges = screen.getByRole("navigation", { name: "Chart timeframe" });
    expect(within(ranges).getByRole("link", { name: "5Y" })).toHaveAttribute(
      "href",
      "/stocks/AAPL?tf=5Y&indicators=&interval=1wk",
    );
  });

  it("labels a partial newest weekly bar and never a daily one", () => {
    expect(partialBarLabel(bar("2026-11-25T00:00:00", "10", true), "1wk")).toBe(
      "Latest week so far (partial), sessions through Nov 25, 2026. It is not a closed bar.",
    );
    expect(partialBarLabel(bar("2026-11-25T00:00:00", "10", true), "1d")).toBeNull();
    expect(partialBarLabel(bar("2026-11-21T00:00:00", "10", false), "1wk")).toBeNull();

    render(
      <PriceChart
        interval="1mo"
        bars={[bar("2026-10-30T00:00:00", "100"), bar("2026-11-25T00:00:00", "101", true)]}
      />,
    );
    expect(screen.getByTestId("partial-bar-label")).toHaveTextContent(
      "Latest month so far (partial)",
    );
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("partial");
  });

  it("draws no partial label when the newest bar is closed", () => {
    render(<PriceChart interval="1wk" bars={[bar("2026-11-21T00:00:00", "100")]} />);
    expect(screen.queryByTestId("partial-bar-label")).not.toBeInTheDocument();
  });
});

describe("backtest universe note (A1.4a)", () => {
  const pinned = {
    name: "pinned",
    point_in_time: false,
    survivorship_biased: true,
    note: "Companies that were delisted are missing.",
  };

  it("states the survivorship flag in one neutral line", () => {
    expect(universeSummary(pinned)).toBe(
      "Pinned symbol list, not point in time: survivorship-biased.",
    );
    render(<UniverseNote universe={pinned} />);
    const note = screen.getByTestId("backtest-universe");
    expect(note).toHaveTextContent("survivorship-biased");
    expect(note).toHaveTextContent("delisted are missing");
    expect(note.className).not.toMatch(/negative|destructive/);
  });

  it("renders nothing without a stamp", () => {
    const { container } = render(<UniverseNote universe={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
