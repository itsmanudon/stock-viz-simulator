import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";

const priceLines: number[] = [];

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "CandlestickSeries",
  HistogramSeries: "HistogramSeries",
  LineSeries: "LineSeries",
  createSeriesMarkers: vi.fn(),
  createChart: () => ({
    addSeries: () => ({
      setData: vi.fn(),
      createPriceLine: ({ price }: { price: number }) => priceLines.push(price),
      priceScale: () => ({ applyOptions: vi.fn() }),
    }),
    priceScale: () => ({ applyOptions: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn(), width: () => 0, setVisibleLogicalRange: vi.fn() }),
    remove: vi.fn(),
  }),
}));

const bar = (ts: string, close: string) => ({
  ts,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
});

describe("PriceChart RSI pane (#73)", () => {
  it("draws RSI in its own pane with 70/30 guides", () => {
    render(
      <PriceChart
        bars={[bar("2026-11-10T00:00:00", "100"), bar("2026-11-11T00:00:00", "101")]}
        rsi={[
          { ts: "2026-11-10T00:00:00", value: 55 },
          { ts: "2026-11-11T00:00:00", value: 61 },
        ]}
      />,
    );
    expect(screen.getByTestId("rsi-pane")).toBeInTheDocument();
    expect(priceLines).toEqual([70, 30]);
  });

  it("has no RSI pane when RSI is not selected", () => {
    render(<PriceChart bars={[bar("2026-11-10T00:00:00", "100")]} rsi={null} />);
    expect(screen.queryByTestId("rsi-pane")).not.toBeInTheDocument();
  });
});
