import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { lwcCalls, resetLwc } from "../stubs/lightweight-charts";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);
vi.mock("@/app/(product)/backtest/actions", () => ({
  saveBacktestRunAction: vi.fn(async () => ({})),
  rerunBacktestRunAction: vi.fn(async () => ({})),
}));
const bars = Array.from({ length: 6 }, (_, i) => ({
  ts: `2024-01-0${i + 1}T00:00:00`,
  open: "100",
  high: "101",
  low: "99",
  close: "100",
  volume: 1000,
}));
vi.mock("@/app/(product)/backtest/strategy-actions", () => ({
  runStrategyAction: vi.fn(),
  strategyBarsAction: vi.fn(async () => bars),
}));
vi.mock("@/lib/api/rules", () => ({
  checkRule: vi.fn(async (rule: string) =>
    rule.includes("??")
      ? {
          valid: false,
          warmup_whole_history: false,
          user_scoped: false,
          error: { kind: "syntax", message: "unexpected '?'", line: 1, column: 7 },
        }
      : {
          valid: true,
          canonical: rule,
          hash: "h",
          type: "boolean series",
          warmup_bars: 50,
          warmup_whole_history: false,
          uses: [],
          user_scoped: false,
        },
  ),
}));

import { RuleStrategyForm } from "@/components/rule-strategy/rule-strategy-form";
import { initialStrategyForm } from "@/components/rule-strategy/rule-strategy-form";
import { RuleStrategyResults } from "@/components/rule-strategy/rule-strategy-results";
import {
  type StrategyResult,
  type StrategyTrade,
  buildStrategyRequest,
  parseTickerList,
  tradeMarkers,
} from "@/lib/rule-strategy";

const SYMBOLS = [
  { ticker: "AAPL", name: "Apple", lastClose: "2024-06-28" },
  { ticker: "MSFT", name: "Microsoft", lastClose: "2024-06-28" },
];

function trade(over: Partial<StrategyTrade> = {}): StrategyTrade {
  return {
    ticker: "AAPL",
    direction: "long",
    entry_date: "2024-01-02",
    entry_price: "100",
    entry_reference_price: "100",
    exit_date: "2024-01-04",
    exit_price: "95",
    exit_reference_price: "95",
    quantity: "20",
    entry_fees: "0",
    exit_fees: "0",
    pnl: "-100",
    return_pct: -0.05,
    reason: "stop_atr",
    gap: true,
    open: false,
    bars_held: 2,
    initial_stop: "95",
    initial_risk: "100",
    r_multiple: -1,
    ...over,
  };
}

const RESULT: StrategyResult = {
  mode: "strategy",
  tickers: ["AAPL"],
  currency: "USD",
  execution_profile: "next_open/v1",
  fee_schedule: "none",
  direction: "long",
  rules: [
    {
      role: "entry",
      text: "e",
      canonical: "close > sma(close, 50)",
      hash: "h",
      setup_version_id: null,
    },
  ],
  stops: { atr: { multiple: 2, period: 14 } },
  sizing: { kind: "fixed_risk", risk_pct: 1 },
  stop_priority: "Within a bar: gaps first.",
  trades: [
    trade(),
    trade({
      entry_date: "2024-01-05",
      exit_date: "2024-01-06",
      reason: "end_of_data",
      open: true,
      gap: false,
      r_multiple: 0.5,
      pnl: "50",
    }),
  ],
  equity_curve: [
    { date: "2024-01-01", nav: "10000" },
    { date: "2024-01-06", nav: "9950" },
  ],
  summary: {
    total_return: -0.005,
    sharpe: -0.2,
    max_drawdown: 0.01,
    final_nav: "9950",
    benchmark_return: 0.01,
    benchmark_final_nav: "10100",
    excess_return: -1.5,
    total_costs: "12",
    gross_return: -0.0038,
    gross_final_nav: "9962",
    total_fees: "10",
    price_costs: "2",
    trade_count: 2,
  },
  benchmark: { kind: "buy_and_hold", tickers: ["AAPL"], total_return: 0.01, final_nav: "10100" },
  source: { kind: "ticker", tickers: ["AAPL"] },
  universe: { name: "pinned", point_in_time: false, survivorship_biased: true, note: "n" },
  warmup_bars: 50,
  unknown_entry_bars: 7,
  unknown_exit_bars: 1,
  ignored_entry_signals: 2,
  skipped_entries: 0,
  skip_reasons: {},
  symbols: [],
  strategy_hash: "a".repeat(64),
  data_fingerprint: "b".repeat(64),
  notes: ["Price return: dividends are not credited in rule strategies."],
};

describe("rule strategy helpers", () => {
  it("parses ticker lists", () => {
    expect(parseTickerList("aapl, msft  nvda;AAPL")).toEqual(["AAPL", "MSFT", "NVDA"]);
  });

  it("builds the request from the form", () => {
    const form = {
      ...initialStrategyForm("AAPL", { from: "2020-01-01", to: "2024-01-01" }),
      useFixed: true,
      useTrail: true,
      trailKind: "pct" as const,
      trailValue: "10",
      useTime: true,
      timeBars: "15",
      universeKind: "list" as const,
      tickerList: "aapl msft",
      maxPositions: "2",
    };
    const req = buildStrategyRequest(form);
    expect(req.entry).toEqual({ rule: "close crosses_above sma(close, 50)" });
    expect(req.universe).toEqual({ tickers: ["AAPL", "MSFT"] });
    expect(req.stops).toEqual({
      fixed_pct: 8,
      atr: { multiple: 2, period: 14 },
      trailing: { kind: "pct", value: 10, period: 14 },
      time_bars: 15,
    });
    expect(req.sizing).toEqual({ kind: "fixed_risk", risk_pct: 1, max_positions: 2 });
    expect(req.shortable).toEqual([]);
    const versioned = buildStrategyRequest({
      ...form,
      entry: { text: "x", versionId: 9 },
      exit: { text: "", versionId: null },
    });
    expect(versioned.entry).toEqual({ setup_version_id: 9 });
    expect(versioned.exit).toBeNull();
  });

  it("puts entries and exits on the chart with the reason and gap", () => {
    const m = tradeMarkers(RESULT.trades, "AAPL", { entry: "g", exit: "r" });
    expect(m.map((x) => x.text)).toEqual(["B", "ATR gap", "B"]);
    expect(m[0]).toMatchObject({ shape: "arrowUp", position: "belowBar", color: "g" });
    const short = tradeMarkers([trade({ direction: "short", gap: false })], "AAPL", {
      entry: "g",
      exit: "r",
    });
    expect(short[0]).toMatchObject({ text: "S", shape: "arrowDown" });
  });
});

describe("RuleStrategyForm", () => {
  beforeEach(() => resetLwc());

  it("runs and shows net-first results", async () => {
    const run = vi.fn(async () => ({ result: RESULT }));
    const user = userEvent.setup();
    render(
      <RuleStrategyForm symbols={SYMBOLS} setups={[]} watchlists={[]} signedIn={false} run={run} />,
    );
    const button = screen.getByRole("button", { name: "Run strategy" });
    await waitFor(() => expect(screen.getAllByTestId("rule-ok")).toHaveLength(2));
    await user.click(button);
    expect(run).toHaveBeenCalledTimes(1);
    const req = (run.mock.calls[0] as unknown[])[0] as ReturnType<typeof buildStrategyRequest>;
    expect(req.universe).toEqual({ ticker: "AAPL" });
    expect(req.sizing).toEqual({ kind: "fixed_risk", risk_pct: 1 });
    const results = await screen.findByTestId("strategy-results");
    const net = within(results).getByLabelText("Net performance");
    expect(net.textContent?.indexOf("Net return")).toBe(0); // net first
    expect(within(results).getByLabelText("Gross and risk").textContent).toContain("Gross return");
    expect(within(results).getByText("Gross return")).toBeTruthy();
    expect(within(results).getByTestId("strategy-counts").textContent).toContain(
      "7 bars with an unknown entry signal",
    );
    expect(screen.getByRole("button", { name: "Save run" })).toBeTruthy();
  });

  it("disables the run while a rule is invalid and watchlists when signed out", async () => {
    const user = userEvent.setup();
    render(
      <RuleStrategyForm
        symbols={SYMBOLS}
        setups={[]}
        watchlists={[]}
        signedIn={false}
        run={vi.fn()}
      />,
    );
    const [entry] = screen.getAllByRole("textbox");
    await user.clear(entry);
    await user.type(entry, "close ??");
    await waitFor(() =>
      expect(screen.getByTestId("rule-error").textContent).toContain("Syntax error"),
    );
    expect(
      (screen.getByRole("button", { name: "Run strategy" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect((screen.getByRole("radio", { name: "Watchlist" }) as HTMLInputElement).disabled).toBe(
      true,
    );
  });

  it("loads a setup version and sends it by id", async () => {
    const run = vi.fn(async () => ({ error: "x", status: 400 }));
    const user = userEvent.setup();
    render(
      <RuleStrategyForm
        symbols={SYMBOLS}
        setups={[
          { versionId: 42, name: "Breakout", rule: "close > highest(high, 20)[1]", preset: true },
        ]}
        watchlists={[{ id: 5, name: "Tech", count: 3 }]}
        signedIn
        run={run}
      />,
    );
    await user.selectOptions(screen.getByRole("combobox", { name: /entry rule/i }), "42");
    await user.click(screen.getByRole("radio", { name: "Watchlist" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Watchlist" }), "5");
    await waitFor(() => expect(screen.getAllByTestId("rule-ok")).toHaveLength(2));
    await user.click(screen.getByRole("button", { name: "Run strategy" }));
    const req = (run.mock.calls[0] as unknown[])[0] as ReturnType<typeof buildStrategyRequest>;
    expect(req.entry).toEqual({ setup_version_id: 42 });
    expect(req.universe).toEqual({ watchlist_id: 5 });
    expect((await screen.findByRole("alert")).textContent).toContain("Check the strategy");
  });
});

describe("RuleStrategyResults", () => {
  beforeEach(() => resetLwc());

  it("lists trades with reason, gap and R, and marks the chart", async () => {
    render(<RuleStrategyResults result={RESULT} />);
    const table = screen.getByTestId("strategy-trades");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("ATR stop");
    expect(rows[0].textContent).toContain("-1.00R");
    expect(within(rows[0]).getByTestId("gap-flag")).toBeTruthy();
    expect(rows[1].textContent).toContain("Still open");
    expect(rows[1].textContent).toContain("(marked)");
    expect(screen.queryByRole("button", { name: "Save run" })).toBeNull();
    await waitFor(() => expect(lwcCalls.markers.some((m) => m.length === 3)).toBe(true));
    expect(screen.getByTestId("strategy-chart-caption").textContent).toContain("AAPL: 2 trades");
  });
});
