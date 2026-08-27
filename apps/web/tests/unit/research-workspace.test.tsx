import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BacktestForm } from "@/components/backtest-form";
import { SignalsTable } from "@/components/signals-table";
import type { BacktestResult } from "@/lib/api";
import { recommendationToSignal } from "@/lib/signals-workspace";

const replace = vi.fn();
const runBacktest = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  usePathname: () => "/backtest",
  useSearchParams: () => new URLSearchParams("ticker=AAPL"),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark" }),
}));

vi.mock("lightweight-charts", () => ({
  AreaSeries: "AreaSeries",
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    runBacktest: (...args: unknown[]) => runBacktest(...args),
  };
});

const success: BacktestResult = {
  ticker: "AAPL",
  trades: [
    { date: "2026-01-15", side: "buy", price: "180", shares: "100" },
    { date: "2026-03-01", side: "sell", price: "200", shares: "100" },
  ],
  equity_curve: [
    { date: "2026-01-02", nav: "100000" },
    { date: "2026-03-01", nav: "112000" },
  ],
  summary: {
    total_return: 0.12,
    sharpe: 1.4,
    max_drawdown: 0.08,
    final_nav: "112000",
    benchmark_return: 0.09,
    benchmark_final_nav: "109000",
    excess_return: 3,
    total_costs: "25.50",
  },
};

describe("BacktestForm", () => {
  beforeEach(() => {
    runBacktest.mockReset();
    replace.mockReset();
  });

  it("shows a meaningful empty state before the first run", () => {
    render(
      <BacktestForm
        symbols={[
          { ticker: "AAPL", name: "Apple Inc." },
          { ticker: "MSFT", name: "Microsoft" },
        ]}
        initialTicker="AAPL"
      />,
    );

    expect(screen.getByRole("heading", { name: "No experiment yet" })).toBeVisible();
    expect(screen.queryByText("Strategy return")).not.toBeInTheDocument();
    expect(screen.getByText(/look-ahead bias/i)).toBeVisible();
    expect(screen.getByLabelText("Commission (bps)")).toBeVisible();
    expect(screen.getByLabelText("Slippage (bps)")).toBeVisible();
  });

  it("prefills ticker from the query and writes it back to the URL", () => {
    render(
      <BacktestForm
        symbols={[
          { ticker: "AAPL", name: "Apple Inc." },
          { ticker: "MSFT", name: "Microsoft" },
        ]}
        initialTicker="MSFT"
      />,
    );

    const select = screen.getByLabelText("Symbol");
    expect(select).toHaveValue("MSFT");
    fireEvent.change(select, { target: { value: "AAPL" } });
    expect(replace).toHaveBeenCalledWith("/backtest?ticker=AAPL", { scroll: false });
  });

  it("renders grouped results including benchmark, excess return, and costs", async () => {
    runBacktest.mockResolvedValue(success);
    render(
      <BacktestForm symbols={[{ ticker: "AAPL", name: "Apple Inc." }]} initialTicker="AAPL" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Equity curve" })).toBeVisible();
    });
    expect(screen.getByText("Strategy return")).toBeVisible();
    expect(screen.getByText("Benchmark return")).toBeVisible();
    expect(screen.getByText("Excess return")).toBeVisible();
    expect(screen.getByText("$25.50")).toBeVisible();
    expect(screen.getByText(/Commission 0 bps/)).toBeVisible();
    expect(screen.getByText(/slippage 0 bps/)).toBeVisible();
    expect(screen.getByText("buy")).toBeVisible();
    expect(runBacktest).toHaveBeenCalledWith(
      expect.objectContaining({
        ticker: "AAPL",
        commission_bps: 0,
        slippage_bps: 0,
      }),
    );
  });

  it("keeps the form and shows a validation error when the API rejects the run", async () => {
    const { ApiError } = await import("@/lib/api");
    runBacktest.mockRejectedValue(
      new ApiError(400, "/v1/backtest", '{"detail":"buy_below must be less than sell_above"}'),
    );
    render(
      <BacktestForm symbols={[{ ticker: "AAPL", name: "Apple Inc." }]} initialTicker="AAPL" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Check the setup");
    });
    expect(screen.getByRole("alert")).toHaveTextContent("buy_below must be less than sell_above");
    expect(screen.getByLabelText("Symbol")).toHaveValue("AAPL");
    expect(screen.queryByRole("heading", { name: "Equity curve" })).not.toBeInTheDocument();
  });
});

describe("SignalsTable", () => {
  it("renders bullish and neutral rows with expandable vote evidence", () => {
    const bullish = recommendationToSignal({
      ticker: "AAPL",
      name: "Apple Inc.",
      sector: "Technology",
      score: 5,
      rationale: [],
      votes: [
        {
          id: "below_mean",
          label: "Below historical mean",
          passed: true,
          detail: "Below historical mean ($70.00 < $88.00)",
        },
        {
          id: "positive_sentiment",
          label: "Positive news sentiment",
          passed: false,
          detail: "No scored headlines in the trailing week",
        },
      ],
      sentiment_7d: 0.22,
      computed_at: "2026-08-26T00:00:00Z",
    });
    const neutral = recommendationToSignal({
      ticker: "MSFT",
      name: "Microsoft",
      sector: "Technology",
      score: 2,
      rationale: [],
      votes: [],
      sentiment_7d: null,
      computed_at: "2026-08-26T00:00:00Z",
    });

    render(
      <SignalsTable
        rows={[bullish, neutral]}
        sort="score"
        dir="desc"
        sortHref={(key) => `/recommendations?sort=${key}`}
      />,
    );

    expect(screen.getByText("Bullish")).toBeVisible();
    expect(screen.getByText("Neutral")).toBeVisible();
    expect(screen.getByText("5/7")).toBeVisible();
    fireEvent.click(screen.getByText("AAPL"));
    expect(screen.getByRole("link", { name: "Open AAPL workspace" })).toHaveAttribute(
      "href",
      "/stocks/AAPL",
    );
    expect(screen.getByRole("link", { name: "Backtest AAPL" })).toHaveAttribute(
      "href",
      "/backtest?ticker=AAPL",
    );
    expect(screen.getAllByText("Below historical mean").length).toBeGreaterThan(0);
    expect(screen.getByText("No scored headlines in the trailing week")).toBeVisible();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByRole("columnheader", { name: "Ticker" })).toHaveAttribute(
      "aria-sort",
      "none",
    );
    expect(screen.getByRole("columnheader", { name: "Strength" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });
});
