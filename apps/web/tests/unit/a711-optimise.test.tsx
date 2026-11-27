// A7.11: the optimiser's URL state, views and result view.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OptimiseResultView } from "@/components/optimise-result";
import { type OptimiseResult, errorDetail, optimiseRequest, parseViews } from "@/lib/optimise";

describe("optimiser request", () => {
  it("builds a bounded request from the URL", () => {
    expect(optimiseRequest({ tickers: "aapl" })).toBeNull();
    const req = optimiseRequest({
      tickers: "aapl, msft MSFT ko",
      method: "black_litterman",
      years: "40",
      rf: "5",
      maxw: "30",
      cash: "100000",
      views: "MSFT 12% 0.6, KO 5 0.4, BAD x 2",
    });
    expect(req).toEqual({
      tickers: ["AAPL", "MSFT", "KO"],
      method: "black_litterman",
      years: 10,
      risk_free_rate: 0.05,
      max_weight: 0.3,
      beta: 0.95,
      delta: 2.5,
      cash: 100000,
      views: [
        { ticker: "MSFT", expected_return: 0.12, confidence: 0.6 },
        { ticker: "KO", expected_return: 0.05, confidence: 0.4 },
      ],
    });
    expect(optimiseRequest({ tickers: "A B", method: "kelly", views: "A 10% 0.5" })).toMatchObject({
      method: "hrp",
      views: [],
      cash: null,
    });
    expect(parseViews("X 10% 1.5")).toEqual([]);
  });

  it("reads the API's detail out of an error", () => {
    expect(
      errorDetail(
        'API 400 /v1/research/optimise: {"detail":"needs 252 common sessions; 90 in the window"}',
      ),
    ).toBe("needs 252 common sessions; 90 in the window");
    expect(errorDetail("API 503 /x: offline")).toBeNull();
  });
});

const result: OptimiseResult = {
  method: "black_litterman",
  currency: "USD",
  first: "2023-11-27",
  last: "2026-11-24",
  sessions: 753,
  risk_free_rate: 0.04,
  beta: 0.95,
  weights: [
    { ticker: "AAPL", weight: 0.6, shares: 30, price: 230.1, prior: 0.08, posterior: 0.09 },
    { ticker: "KO", weight: 0.4, shares: 80, price: 70.25, prior: 0.05, posterior: 0.06 },
  ],
  performance: { expected_return: 0.11, volatility: 0.18, sharpe: 0.39, cvar: 0.031 },
  equal_weight: { expected_return: 0.1, volatility: 0.2, sharpe: 0.3, cvar: 0.034 },
  cash: 20000,
  leftover: 476.75,
  notes: ["In-sample on 753 common sessions; not a forecast and not advice."],
  disclaimer: "Weights fitted to the stored past, in-sample. Not a recommendation.",
};

describe("OptimiseResultView", () => {
  it("shows weights, shares, prior and posterior and never colours gains", () => {
    const { container } = render(<OptimiseResultView result={result} />);
    const rows = screen.getAllByTestId("optimise-row");
    expect(within(rows[0]).getByText("60.0%")).toBeTruthy();
    expect(within(rows[0]).getByText("30")).toBeTruthy();
    expect(within(rows[1]).getByText("6.0%")).toBeTruthy();
    expect(screen.getByTestId("optimise-leftover").textContent).toContain("$476.75");
    expect(screen.getByText(/753 common sessions \(2023-11-27/)).toBeTruthy();
    expect(container.querySelector(".text-positive, .text-negative")).toBeNull();
  });
});
