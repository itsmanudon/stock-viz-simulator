// A7.13: lender mode's card and the desk presets' links.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LenderCard, lenderScatter } from "@/components/lender-card";
import type { Lender } from "@/lib/api/fundamentals";
import { DESKS, type Desk, deskById, deskChartHref, deskScreenHref } from "@/lib/desks";

function desk(id: string): Desk {
  const found = deskById(id);
  if (!found) throw new Error(`no desk ${id}`);
  return found;
}

const lender: Lender = {
  ticker: "SBIN.NS",
  market: "IN",
  pb: 1.4,
  roe: 17,
  as_of: "2026-11-26",
  peers: [
    { ticker: "HDFCBANK.NS", pb: 2.1, roe: 16 },
    { ticker: "SBIN.NS", pb: 1.4, roe: 17 },
    { ticker: "ICICIBANK.NS", pb: 2.3, roe: 18 },
  ],
  slope: 0.1,
  intercept: 0.5,
  line_pb: 2.2,
  gap: -0.8,
  coe: 0.12,
  growth: 0.06,
  justified_pb: 1.83,
  reasons: [],
  method: "Least squares of P/B on ROE.",
  kpi_note: "GNPA, NNPA, NIM, CASA and capital adequacy are not in any free source.",
};

describe("lender card", () => {
  it("shows the figures, the scatter and the missing KPIs", () => {
    render(<LenderCard lender={lender} />);
    const figures = screen.getAllByTestId("lender-figure").map((e) => e.textContent);
    expect(figures).toEqual(["1.40", "17.0%", "2.20", "-0.80", "1.83"]);
    expect(screen.getByTestId("lender-scatter").querySelectorAll("circle")).toHaveLength(3);
    expect(screen.getByText(/GNPA, NNPA/)).toBeTruthy();
    const plot = lenderScatter(lender);
    expect(plot?.line).not.toBeNull();
  });

  it("renders nothing without data", () => {
    const { container } = render(<LenderCard lender={null} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("desks", () => {
  it("has the four presets with chart and screen links", () => {
    expect(DESKS.map((d) => d.id)).toEqual(["swing", "compounder", "derivatives", "quant"]);
    expect(deskChartHref(desk("swing"), " tcs.ns ")).toBe(
      "/stocks/TCS.NS?indicators=ema_20%2Csma_50%2Crsi_14%2Crsline",
    );
    const comp = desk("compounder");
    expect(deskChartHref(comp, "AAPL")).toBe(
      "/stocks/AAPL?indicators=sma_200&type=line&tab=financials",
    );
    expect(deskScreenHref(comp)).toBe("/screener?roe_min=15&de_max=1&sort=mcap&dir=desc");
    expect(deskById("nope")).toBeUndefined();
  });
});
