import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OverfittingChecks } from "@/components/report-card/overfitting-checks";
import { ReportCard } from "@/components/report-card/report-card";
import { PboPanel, PlateauHeatmap } from "@/components/report-card/sweep-checks";
import {
  type ReportCard as Card,
  type OverfittingChecks as Checks,
  type Plateau,
  formatMetric,
  heatShare,
  probabilityWords,
  templateRoundTrips,
} from "@/lib/report-card";

const unlock = vi.fn();
vi.mock("@/app/(product)/backtest/holdout-actions", () => ({
  unlockHoldoutAction: (...args: unknown[]) => unlock(...args),
  runTemplateAction: vi.fn(),
}));

const card: Card = {
  metrics: [
    { key: "cagr", label: "CAGR", value: 0.1234, unit: "pct", formula: "(final / cash)^(1/y) - 1" },
    { key: "win_rate", label: "Win rate", value: 0.5, unit: "pct", formula: "wins / closed" },
    {
      key: "expectancy_r",
      label: "Expectancy (R)",
      value: null,
      unit: "r",
      formula: "mean R",
      note: "No stop",
    },
    { key: "expectancy", label: "Expectancy", value: 12.5, unit: "money", formula: "mean P&L" },
  ],
  sharpe: {
    observations: 250,
    sharpe: 0.05,
    sharpe_annual: 0.79,
    skewness: -0.2,
    kurtosis: 4.1,
    risk_free_rate: 0.05,
    psr: 0.88,
    benchmark_sharpe: 0,
    formula: "PSR formula",
  },
  monte_carlo: {
    method: "stationary_block_bootstrap",
    paths: 2000,
    mean_block: 5,
    seed: 20261126,
    horizon_days: 250,
    max_drawdown: { p5: 0.05, p50: 0.12, p95: 0.25 },
    final_nav: { p5: 900, p50: 1100, p95: 1400 },
    prob_loss: 0.3,
    actual_max_drawdown: 0.1,
    fan: [
      { date: "2024-01-01", p5: 1000, p50: 1000, p95: 1000 },
      { date: "2024-12-31", p5: 900, p50: 1100, p95: 1400 },
    ],
  },
  regimes: {
    method: "rules on past data",
    rows: [],
    reason: "No stored bars for ^GSPC.",
    index_sessions: 0,
    breadth_sessions: 0,
  },
};

const checks: Checks = {
  trials: {
    family_key: "k",
    family_label: "SMA crossover · AAPL",
    definition: "one idea",
    scope: "user",
    n: 3,
    runs: 4,
    sharpe_variance: 0.001,
    sharpe_annual_values: [0.5, 0.8, 1.1],
  },
  dsr: {
    n: 3,
    sharpe: 0.05,
    sharpe_annual: 0.79,
    observations: 250,
    variance: 0.001,
    expected_max_sharpe: 0.03,
    expected_max_sharpe_annual: 0.48,
    value: 0.62,
    formula: "DSR formula",
    note: "Deflated for 3 variants",
    meaning: "About a 62% chance",
  },
  holdout: {
    mode: "last_20pct",
    status: "locked",
    holdout_from: "2023-01-01",
    holdout_to: "2023-12-31",
    can_unlock: true,
    note: "Holdout locked",
  },
};

describe("report card", () => {
  it("formats each unit and says n/a for null", () => {
    expect(formatMetric(card.metrics[0], "USD")).toBe("+12.34%");
    expect(formatMetric(card.metrics[2], "USD")).toBe("n/a");
    expect(formatMetric(card.metrics[3], "INR")).toBe("₹12.50");
    expect(probabilityWords(0.97)).toBe("strong");
    expect(probabilityWords(null)).toBe("not defined");
  });

  it("shows metrics with formulas on request, the fan and the regime reason", () => {
    render(<ReportCard report={card} currency="USD" />);
    expect(screen.getByText("CAGR")).toBeVisible();
    const tips = screen.getAllByTestId("formula-tip");
    fireEvent.click(tips[0]);
    expect(screen.getByRole("tooltip")).toHaveTextContent("(final / cash)^(1/y) - 1");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.getByTestId("mc-fan")).toHaveTextContent("seed 20261126");
    expect(screen.getByTestId("regime-split")).toHaveTextContent("No stored bars for ^GSPC.");
  });

  it("unlocks the holdout in two steps and then shows it as seen", async () => {
    unlock.mockResolvedValue({
      checks: {
        ...checks,
        holdout: {
          ...checks.holdout,
          status: "seen",
          can_unlock: false,
          unlocked_at: "2026-11-26T10:00:00",
          note: "Holdout seen",
          result: {
            from_date: "2023-01-01",
            to_date: "2023-12-31",
            total_return: 0.04,
            sharpe: 0.6,
            max_drawdown: 0.07,
            psr: 0.7,
            trades: 3,
          },
        },
      },
    });
    const request = { backtest: { ticker: "AAPL" } as never };
    render(<OverfittingChecks checks={checks} report={card} request={request} />);
    expect(screen.getByTestId("trials-n")).toHaveTextContent("3");
    expect(screen.getByTestId("dsr-value")).toHaveTextContent("62.0%");
    expect(screen.getByTestId("holdout-panel")).toHaveAttribute("data-status", "locked");
    fireEvent.click(screen.getByTestId("holdout-unlock"));
    expect(unlock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("holdout-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("holdout-panel")).toHaveAttribute("data-status", "seen"),
    );
    expect(unlock).toHaveBeenCalledWith(request);
    expect(screen.getByText("Holdout net return")).toBeVisible();
  });
});

const peak: Plateau = {
  metric: "sharpe",
  x_param: "short_window",
  y_param: "long_window",
  x_values: [5, 10],
  y_values: [50, 100],
  cells: [
    [0.1, 2.0],
    [null, 0.2],
  ],
  best: { x: 10, y: 50, value: 2.0 },
  tolerance: 0.25,
  neighbours: 2,
  within: 0,
  share_within: 0,
  isolated: true,
  rule: "rule",
};

describe("sweep checks", () => {
  it("warns about an isolated peak and switches metric", () => {
    const flat = { ...peak, metric: "total_return", isolated: false, within: 2 };
    render(<PlateauHeatmap plateaus={{ sharpe: peak, total_return: flat }} />);
    expect(screen.getByTestId("plateau-isolated")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Net return"));
    expect(screen.getByTestId("plateau-ok")).toBeVisible();
    expect(heatShare(peak)[1][0]).toBeNull();
  });

  it("shows PBO or why it is missing", () => {
    const { rerender } = render(<PboPanel pbo={null} reason="Needs two settings." />);
    expect(screen.getByText("Needs two settings.")).toBeVisible();
    rerender(
      <PboPanel
        pbo={{
          method: "cscv",
          pbo: 0.4,
          blocks: 16,
          block_sessions: 50,
          dropped_sessions: 3,
          sessions: 803,
          settings: 15,
          combinations: 12870,
          metric: "sharpe",
          logit_median: 0.2,
          prob_oos_loss: 0.3,
          histogram: [{ lo: -0.5, hi: 0, count: 5 }],
        }}
      />,
    );
    expect(screen.getByTestId("pbo-value")).toHaveTextContent("40.0%");
  });

  it("pairs template legs into round trips", () => {
    const trips = templateRoundTrips(
      [
        { date: "2024-01-02", side: "buy", price: "10", shares: "1" },
        { date: "2024-01-05", side: "sell", price: "12", shares: "1" },
        { date: "2024-02-01", side: "buy", price: "11", shares: "1" },
      ],
      "AAPL",
      "2024-03-01",
    );
    expect(trips.map((t) => [t.entry_date, t.exit_date, t.open])).toEqual([
      ["2024-01-02", "2024-01-05", false],
      ["2024-02-01", "2024-03-01", true],
    ]);
  });
});
