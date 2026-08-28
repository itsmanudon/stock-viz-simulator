import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BacktestForm } from "@/components/backtest-form";
import { SignalsTable } from "@/components/signals-table";
import type { BacktestResult } from "@/lib/api";
import { recommendationToSignal } from "@/lib/signals-workspace";

const replace = vi.fn();
const push = vi.fn();
const runBacktest = vi.fn();
let searchQuery = "ticker=AAPL";
let pathname = "/backtest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(window.location.search || searchQuery),
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
    push.mockReset();
    searchQuery = "ticker=AAPL";
    pathname = "/backtest";
    window.history.replaceState(null, "", `${pathname}?${searchQuery}`);
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

  it("replaces prior results with a running state instead of leaving stale metrics", async () => {
    let finish: ((value: BacktestResult) => void) | undefined;
    runBacktest.mockImplementationOnce(
      () =>
        new Promise<BacktestResult>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <BacktestForm symbols={[{ ticker: "AAPL", name: "Apple Inc." }]} initialTicker="AAPL" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(screen.getByText(/Running the rule over stored daily bars/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "No experiment yet" })).not.toBeInTheDocument();

    finish?.(success);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Equity curve" })).toBeVisible();
    });

    let finishSecond: ((value: BacktestResult) => void) | undefined;
    runBacktest.mockImplementationOnce(
      () =>
        new Promise<BacktestResult>((resolve) => {
          finishSecond = resolve;
        }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(screen.getByText(/Running the rule over stored daily bars/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Equity curve" })).not.toBeInTheDocument();
    finishSecond?.(success);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Equity curve" })).toBeVisible();
    });
  });
});

describe("SignalsTable", () => {
  function renderSignals() {
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

    pathname = "/recommendations";
    window.history.replaceState(null, "", `${pathname}?${searchQuery}`);
    return render(
      <SignalsTable
        rows={[bullish, neutral]}
        sort="score"
        dir="desc"
        sortHrefs={{
          score: "/recommendations?sort=score",
          ticker: "/recommendations?sort=ticker",
          sentiment: "/recommendations?sort=sentiment",
          updated: "/recommendations?sort=updated",
        }}
      />,
    );
  }

  it("renders a full scan view and moves evidence into a selected detail pane", () => {
    renderSignals();

    expect(screen.getByText("Bullish")).toBeVisible();
    expect(screen.getByText("Neutral")).toBeVisible();
    expect(screen.getByText("5/7")).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Ticker" })).toHaveAttribute(
      "aria-sort",
      "none",
    );
    expect(screen.getByRole("columnheader", { name: "Strength" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    const list = screen.getByRole("region", { name: "Signals list" });
    expect(list).toHaveClass("h-full", "min-h-0");
    expect(list.querySelector("ul")).toHaveClass("lg:flex-1", "lg:overflow-y-auto");
    expect(screen.queryByRole("heading", { name: "Seven vote checks" })).not.toBeInTheDocument();
    expect(document.querySelector("details")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /AAPL, Apple Inc\./ }));

    expect(screen.getByRole("heading", { name: "Apple Inc." })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Seven vote checks" })).toBeVisible();
    expect(screen.getByText("Below historical median")).toBeVisible();
    expect(screen.getByText("Within 1 stdev below mean")).toBeVisible();
    expect(screen.getByText("Volume above average")).toBeVisible();
    expect(screen.getByText("3-bar uptrend")).toBeVisible();
    expect(screen.getByText("Positive 5-bar slope")).toBeVisible();
    expect(screen.getAllByText("Not passed")).toHaveLength(6);
    expect(screen.getByText(/Computed Aug 26, 2026/)).toBeVisible();
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
    expect(screen.getByRole("button", { name: /AAPL, Apple Inc\./ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const detail = screen.getByText("Signal detail").closest("section");
    expect(detail).toHaveClass("h-full", "min-h-0", "animate-in", "fade-in-0");
    expect(detail).not.toHaveClass("slide-in-from-left-1", "slide-in-from-right-1");
    expect(detail?.parentElement).toHaveClass("transition-opacity");
    expect(detail?.parentElement).not.toHaveClass("translate-x-0", "translate-x-3");
  });

  it("fades ticker content when switching and keeps native-history sync idempotent", async () => {
    searchQuery = "";
    renderSignals();

    fireEvent.click(screen.getByRole("button", { name: /AAPL, Apple Inc\./ }));
    const firstDetail = screen.getByText("Signal detail").closest("section");
    expect(firstDetail).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /MSFT, Microsoft/ }));
    const switchedDetail = screen.getByText("Signal detail").closest("section");
    expect(screen.getByRole("heading", { name: "Microsoft" })).toBeVisible();
    expect(switchedDetail).not.toHaveClass("slide-in-from-left-1", "slide-in-from-right-1");
    expect(switchedDetail).toHaveClass("animate-in", "fade-in-0");
    expect(switchedDetail).not.toBe(firstDetail);

    window.history.replaceState(null, "", "/recommendations?selected=MSFT");
    fireEvent.popState(window);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Microsoft" })).toBeVisible();
    });
    expect(screen.getByText("Signal detail").closest("section")).toBe(switchedDetail);
  });

  it("preserves current filters and sort state when selecting and closing", () => {
    searchQuery = "min=4&signal=bullish&sort=ticker&dir=asc&q=app";
    renderSignals();
    const pushState = vi.spyOn(window.history, "pushState");
    const replaceState = vi.spyOn(window.history, "replaceState");

    fireEvent.click(screen.getByRole("button", { name: /AAPL, Apple Inc\./ }));
    expect(push).not.toHaveBeenCalled();
    expect(pushState).toHaveBeenLastCalledWith(
      null,
      "",
      "/recommendations?min=4&signal=bullish&sort=ticker&dir=asc&q=app&selected=AAPL",
    );

    fireEvent.click(screen.getByRole("button", { name: "Back to signals" }));
    const closingWrapper = screen.getByText("Signal detail").closest("section")?.parentElement;
    expect(closingWrapper).toHaveClass("opacity-0");
    expect(closingWrapper).not.toHaveClass("hidden");
    expect(replace).not.toHaveBeenCalled();
    expect(replaceState).toHaveBeenLastCalledWith(
      null,
      "",
      "/recommendations?min=4&signal=bullish&sort=ticker&dir=asc&q=app",
    );
    return waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Seven vote checks" })).not.toBeInTheDocument();
    });
  });

  it("closes the detail pane with Escape and ignores an invalid URL selection", () => {
    searchQuery = "selected=UNKNOWN&min=4";
    const invalidRender = renderSignals();
    expect(screen.queryByRole("heading", { name: "Seven vote checks" })).not.toBeInTheDocument();

    invalidRender.unmount();
    searchQuery = "ticker=AAPL";
    renderSignals();
    fireEvent.click(screen.getByRole("button", { name: /AAPL, Apple Inc\./ }));
    fireEvent.keyDown(window, { key: "Escape" });

    expect(replace).not.toHaveBeenCalled();
    expect(window.location.pathname + window.location.search).toBe("/recommendations?ticker=AAPL");
    return waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Seven vote checks" })).not.toBeInTheDocument();
    });
  });

  it("syncs selected detail from browser back and forward without router navigation", async () => {
    searchQuery = "";
    renderSignals();
    const apple = screen.getByRole("button", { name: /AAPL, Apple Inc\./ });
    const pushState = vi.spyOn(window.history, "pushState");

    fireEvent.click(apple);
    expect(pushState).toHaveBeenLastCalledWith(null, "", "/recommendations?selected=AAPL");
    expect(screen.getByRole("heading", { name: "Seven vote checks" })).toBeVisible();

    window.history.replaceState(null, "", "/recommendations");
    fireEvent.popState(window);
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Seven vote checks" })).not.toBeInTheDocument();
    });

    window.history.replaceState(null, "", "/recommendations?selected=AAPL");
    fireEvent.popState(window);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Seven vote checks" })).toBeVisible();
    });
    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });
});
