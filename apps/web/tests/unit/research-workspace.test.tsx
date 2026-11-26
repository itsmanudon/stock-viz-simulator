import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BacktestForm } from "@/components/backtest-form";
import type { BacktestResult } from "@/lib/api";

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
    timeScale: () => ({ fitContent: vi.fn(), width: () => 0, setVisibleLogicalRange: vi.fn() }),
    remove: vi.fn(),
  }),
}));

const saveRun = vi.fn(async () => ({ runId: 7 }));
vi.mock("@/app/(product)/backtest/actions", () => ({
  saveBacktestRunAction: (...args: unknown[]) => saveRun(...(args as [])),
  rerunBacktestRunAction: vi.fn(async () => ({})),
}));

// A4.3: template runs go through a server action; adapt it to the mock.
vi.mock("@/app/(product)/backtest/holdout-actions", () => ({
  runTemplateAction: async (request: unknown) => {
    try {
      return { result: await runBacktest(request) };
    } catch (err) {
      const e = err as { status?: number; message?: string };
      const raw = (e.message ?? "").replace(/^API \d+ [^:]+:\s*/, "");
      let message = raw;
      try {
        message = (JSON.parse(raw) as { detail: string }).detail;
      } catch {
        // plain text
      }
      return { error: message, status: e.status ?? 500 };
    }
  },
  unlockHoldoutAction: vi.fn(async () => ({})),
}));

vi.mock("@/components/rule-strategy/strategy-trades-chart", () => ({
  StrategyTradesChart: () => null,
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
    gross_return: 0.12,
    gross_final_nav: "112025.50",
    total_fees: "25.50",
    price_costs: "0",
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
    expect(screen.queryByText("Net return")).not.toBeInTheDocument();
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

  it("moves the date range to the chosen symbol's history until dates are edited", () => {
    render(
      <BacktestForm
        symbols={[
          { ticker: "AAPL", name: "Apple Inc.", lastClose: "2025-04-04" },
          { ticker: "MSFT", name: "Microsoft", lastClose: "2025-03-01" },
          { ticker: "ZZZ", name: "No bars", lastClose: null },
        ]}
        initialTicker="AAPL"
      />,
    );

    expect(screen.getByLabelText("To")).toHaveValue("2025-04-04");
    expect(screen.getByText("Stored closes for AAPL end Apr 4, 2025.")).toBeVisible();
    expect(screen.getByRole("option", { name: /ZZZ .*no stored history/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "MSFT" } });
    expect(screen.getByLabelText("From")).toHaveValue("2024-03-01");
    expect(screen.getByLabelText("To")).toHaveValue("2025-03-01");

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2024-06-01" } });
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "AAPL" } });
    expect(screen.getByLabelText("From")).toHaveValue("2024-06-01");
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
    expect(screen.getByText("Net return")).toBeVisible();
    expect(screen.getByText("Gross return")).toBeVisible();
    expect(screen.getByText("Benchmark return")).toBeVisible();
    expect(screen.getByText("Excess return")).toBeVisible();
    expect(screen.getByText("$25.50")).toBeVisible();
    expect(screen.getByText(/Commission 0 bps/)).toBeVisible();
    expect(screen.getByText(/slippage 0 bps/)).toBeVisible();
    expect(screen.getByText("Buy")).toBeVisible();
    expect(runBacktest).toHaveBeenCalledWith(
      expect.objectContaining({
        ticker: "AAPL",
        commission_bps: 0,
        slippage_bps: 0,
        fill_rule: "next_open",
        spread_bps: 0,
        fee_schedule: "auto",
        brokerage: "zerodha",
        adv_cap_pct: 10,
      }),
    );
  });

  it("states the run's currency, return mode, basis and warm-up (Phase 5.2)", async () => {
    runBacktest.mockResolvedValue({
      ...success,
      ticker: "SAP.DE",
      currency: "EUR",
      price_basis: "mixed",
      return_mode: "total",
      warmup_bars: 250,
    } satisfies BacktestResult);
    render(<BacktestForm symbols={[{ ticker: "SAP.DE", name: "SAP" }]} initialTicker="SAP.DE" />);
    fireEvent.change(screen.getByLabelText("Returns"), { target: { value: "total" } });
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    await waitFor(() => {
      expect(screen.getByTestId("backtest-basis")).toBeVisible();
    });
    const note = screen.getByTestId("backtest-basis").textContent ?? "";
    expect(note).toContain("Amounts in EUR.");
    expect(note).toContain("dividends are credited");
    expect(note).toContain("mixed");
    expect(note).toContain("250 bars before the start");
    expect(screen.getByText("€25.50")).toBeVisible();
    expect(runBacktest).toHaveBeenCalledWith(expect.objectContaining({ return_mode: "total" }));
  });

  it("offers to save the run it just showed (Phase 5.4)", async () => {
    runBacktest.mockResolvedValue(success);
    render(
      <BacktestForm symbols={[{ ticker: "AAPL", name: "Apple Inc." }]} initialTicker="AAPL" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    const save = await screen.findByRole("button", { name: "Save run" });
    fireEvent.click(save);
    await waitFor(() => expect(saveRun).toHaveBeenCalled());
    expect(await screen.findByText(/Stored as run 7/)).toBeVisible();
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
