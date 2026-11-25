import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";

import { lwcCalls, resetLwc } from "../stubs/lightweight-charts";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const bar = (ts: string, close: string) => ({
  ts,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
});

beforeEach(() => {
  resetLwc();
  window.localStorage.clear();
});

describe("PriceChart RSI pane (#73)", () => {
  it("draws RSI in its own pane of the one chart with 70/30 guides", () => {
    render(
      <PriceChart
        bars={[bar("2026-11-10T00:00:00", "100"), bar("2026-11-11T00:00:00", "101")]}
        rsi={[
          { ts: "2026-11-10T00:00:00", value: 55 },
          { ts: "2026-11-11T00:00:00", value: 61 },
        ]}
      />,
    );
    expect(screen.getByTestId("pane-rsi")).toBeInTheDocument();
    expect(lwcCalls.charts).toBe(1);
    const rsi = lwcCalls.series.find((s) => s.pane === 2);
    expect(rsi?.type).toBe("LineSeries");
    expect(rsi?.priceLines).toEqual([70, 30]);
  });

  it("has no RSI pane when RSI is not selected", () => {
    render(<PriceChart bars={[bar("2026-11-10T00:00:00", "100")]} rsi={null} />);
    expect(screen.queryByTestId("pane-rsi")).not.toBeInTheDocument();
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-panes", "price,volume");
  });
});
