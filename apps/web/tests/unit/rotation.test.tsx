import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);
vi.mock("@/app/(product)/backtest/actions", () => ({
  saveBacktestRunAction: vi.fn(async () => ({})),
  rerunBacktestRunAction: vi.fn(async () => ({})),
}));
vi.mock("@/app/(product)/backtest/holdout-actions", () => ({
  unlockHoldoutAction: vi.fn(async () => ({})),
  runTemplateAction: vi.fn(async () => ({})),
}));
vi.mock("@/app/(product)/backtest/rotation-actions", () => ({ runRotationAction: vi.fn() }));
const checks: string[] = [];
vi.mock("@/lib/api/rules", () => {
  const answer = (rule: string, number: boolean) =>
    number && rule.includes(">")
      ? {
          valid: false,
          warmup_whole_history: false,
          user_scoped: false,
          error: { kind: "type", message: "a ranking must be a number", line: 1, column: 1 },
        }
      : {
          valid: true,
          canonical: rule,
          hash: "h",
          type: number ? "number series" : "boolean series",
          warmup_bars: 126,
          warmup_whole_history: false,
          uses: [],
          user_scoped: false,
        };
  return {
    checkRule: vi.fn(async (rule: string) => answer(rule, false)),
    checkNumber: vi.fn(async (rule: string) => {
      checks.push(rule);
      return answer(rule, true);
    }),
  };
});

import { RotationForm } from "@/components/rotation/rotation-form";
import { RotationResults } from "@/components/rotation/rotation-results";
import {
  type RotationResult,
  buildRotationRequest,
  initialRotationForm,
  marketTickers,
  rebalanceSummary,
  rotationProblem,
  rotationRange,
  symbolMarket,
} from "@/lib/rotation";

const SYMBOLS = [
  { ticker: "AAPL", name: "Apple", lastClose: "2025-04-07" },
  { ticker: "MSFT", name: "Microsoft", lastClose: "2025-04-07" },
  { ticker: "NVDA", name: "Nvidia", lastClose: "2025-04-07" },
  { ticker: "IBM", name: "IBM", lastClose: null },
  { ticker: "TCS.NS", name: "TCS", lastClose: "2025-04-07" },
  { ticker: "^GSPC", name: "S&P 500", lastClose: "2025-04-07" },
];

function result(): RotationResult {
  return {
    mode: "rotation",
    tickers: ["AAPL", "MSFT", "NVDA"],
    currency: "USD",
    execution_profile: "next_open/v1",
    fee_schedule: "none",
    rules: [
      {
        role: "ranking",
        text: "pct_change(close, 126)",
        canonical: "pct_change(close, 126)",
        hash: "h",
      },
    ],
    top_n: 2,
    schedule: "monthly",
    weighting: "equal",
    buffer: 0,
    venue: "XNYS",
    timing: "Ranks on the last session of each month.",
    rebalances: [
      {
        signal_date: "2024-12-31",
        trade_dates: ["2025-01-02"],
        equity: "100000",
        ranked: [
          { ticker: "NVDA", value: 40.5, rank: 1 },
          { ticker: "AAPL", value: 12.25, rank: 2 },
          { ticker: "MSFT", value: 3, rank: 3 },
        ],
        unranked: [],
        held_before: [],
        held_after: ["NVDA", "AAPL"],
        entered: ["NVDA", "AAPL"],
        exited: [],
        turnover: 0.5,
      },
      {
        signal_date: "2025-01-31",
        trade_dates: ["2025-02-03"],
        equity: "101000",
        ranked: [],
        unranked: [{ ticker: "AAPL", reason: "unknown" }],
        held_before: ["NVDA", "AAPL"],
        held_after: ["NVDA", "MSFT"],
        entered: ["MSFT"],
        exited: ["AAPL"],
        turnover: 0.25,
      },
    ],
    trades: [
      {
        ticker: "AAPL",
        entry_date: "2025-01-02",
        entry_price: "100",
        entry_reference_price: "100",
        exit_date: "2025-02-03",
        exit_price: "110",
        exit_reference_price: "110",
        quantity: "500",
        entry_fees: "0",
        exit_fees: "0",
        pnl: "5000",
        return_pct: 0.1,
        reason: "rebalance",
        open: false,
        bars_held: 21,
      },
    ],
    equity_curve: [
      { date: "2025-01-02", nav: "100000" },
      { date: "2025-02-28", nav: "105000" },
    ],
    summary: {
      total_return: 0.05,
      sharpe: 1.2,
      max_drawdown: 0.03,
      final_nav: "105000",
      benchmark_return: 0.02,
      excess_return: 3,
      gross_return: 0.051,
      total_costs: "100",
      total_fees: "50",
    },
    benchmark: {
      kind: "equal_weight_buy_and_hold",
      tickers: ["AAPL", "MSFT", "NVDA"],
      total_return: 0.02,
      final_nav: "102000",
    },
    turnover: {
      rebalances: 2,
      mean_per_rebalance: 0.375,
      total: 0.75,
      annualised: 4.5,
      definition: "One-way turnover.",
    },
    source: { kind: "list", tickers: ["AAPL", "MSFT", "NVDA"] },
    universe: {
      name: "pinned",
      point_in_time: false,
      survivorship_biased: true,
      note: "Pinned list.",
    },
    strategy_hash: "a".repeat(64),
    data_fingerprint: "b".repeat(64),
  } as unknown as RotationResult;
}

describe("rotation helpers", () => {
  it("tells markets apart and picks symbols with closes", () => {
    expect(symbolMarket("AAPL")).toBe("US");
    expect(symbolMarket("TCS.NS")).toBe("IN");
    expect(symbolMarket("^GSPC")).toBeNull();
    expect(symbolMarket("VOD.L")).toBeNull();
    expect(marketTickers(SYMBOLS, "US")).toEqual(["AAPL", "MSFT", "NVDA"]);
    expect(marketTickers(SYMBOLS, "IN")).toEqual(["TCS.NS"]);
    expect(rotationRange("2025-04-07")).toEqual({ from: "2015-04-07", to: "2025-04-07" });
  });

  it("builds the request, with and without a cash filter", () => {
    const form = initialRotationForm(["AAPL", "MSFT"], { from: "2015-01-01", to: "2025-01-01" });
    const plain = buildRotationRequest(form);
    expect(plain).toMatchObject({
      ranking: "pct_change(close, 126)",
      top_n: 5,
      schedule: "monthly",
      weighting: "equal",
      cash_filter: null,
      universe: { tickers: ["AAPL", "MSFT"] },
      adv_cap_pct: 10,
      holdout: "last_20pct",
    });
    const filtered = buildRotationRequest({ ...form, useCashFilter: true });
    expect(filtered.cash_filter).toEqual({ rule: "index_close < sma(index_close, 200)" });
  });

  it("explains why it cannot run", () => {
    const form = initialRotationForm(["AAPL", "MSFT"], { from: "2015-01-01", to: "2025-01-01" });
    expect(rotationProblem(form, true)).toMatch(/more than the 2 tickers/);
    expect(rotationProblem({ ...form, topN: "2" }, true)).toBeNull();
    expect(rotationProblem({ ...form, topN: "2" }, false)).toMatch(/Fix the ranking/);
    expect(rotationProblem({ ...form, tickerList: "AAPL" }, true)).toMatch(/two tickers/);
  });

  it("summarises a rebalance", () => {
    const [first, second] = result().rebalances;
    expect(rebalanceSummary(first)).toBe("2 in, 0 out");
    expect(rebalanceSummary(second)).toBe("1 in, 1 out");
    expect(rebalanceSummary({ ...second, cash_filter: true })).toMatch(/Cash filter met/);
  });
});

describe("RotationForm", () => {
  it("checks the ranking as a number and runs", async () => {
    const run = vi.fn(async () => ({ result: result() }));
    render(
      <RotationForm symbols={SYMBOLS} setups={[]} watchlists={[]} signedIn={false} run={run} />,
    );
    const list = screen.getByLabelText(/Tickers \(2 to 50/);
    expect((list as HTMLTextAreaElement).value).toBe("AAPL, MSFT, NVDA");
    await userEvent.clear(screen.getByLabelText("Top N"));
    await userEvent.type(screen.getByLabelText("Top N"), "2");
    const ranking = screen.getByLabelText(/Ranking/);
    await userEvent.clear(ranking);
    await userEvent.type(ranking, "close > open");
    await waitFor(() => expect(screen.getByTestId("rule-error")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Run rotation" })).toHaveProperty("disabled", true);
    await userEvent.clear(ranking);
    await userEvent.type(ranking, "pct_change(close, 63)");
    await waitFor(() => expect(screen.getByTestId("rule-ok")).toBeTruthy());
    expect(checks.at(-1)).toBe("pct_change(close, 63)");
    await userEvent.click(screen.getByRole("button", { name: "Run rotation" }));
    await waitFor(() => expect(screen.getByTestId("rotation-results")).toBeTruthy());
    expect(run).toHaveBeenCalledWith(
      expect.objectContaining({ ranking: "pct_change(close, 63)", top_n: 2 }),
    );
    await userEvent.click(screen.getByRole("button", { name: "All India (1)" }));
    expect((list as HTMLTextAreaElement).value).toBe("TCS.NS");
  });
});

describe("RotationResults", () => {
  it("lists holdings per rebalance newest first with turnover and the ranking", () => {
    render(<RotationResults result={result()} />);
    const table = screen.getByTestId("rotation-rebalances");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("NVDA, MSFT");
    expect(rows[0].textContent).toContain("25.0%");
    expect(rows[1].textContent).toContain("NVDA, AAPL");
    expect(rows[1].textContent).toContain("40.50");
    expect(screen.getByText("450.0% a year")).toBeTruthy();
    expect(screen.getByRole("link", { name: "AAPL" }).getAttribute("href")).toBe("/stocks/AAPL");
  });
});
