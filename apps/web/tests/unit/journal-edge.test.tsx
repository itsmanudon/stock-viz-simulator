import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  EdgeDriftCard,
  EdgeGroupsTable,
  EdgeHonesty,
  EdgeOverview,
} from "@/components/journal/edge-view";
import {
  type EdgeDrift,
  type EdgeGroup,
  type EdgeStats,
  edgeHref,
  edgeQuery,
  moneyInterval,
  pct,
  rInterval,
} from "@/lib/journal-edge";

function group(overrides: Partial<EdgeGroup> = {}): EdgeGroup {
  return {
    key: "setup:5",
    label: "Breakout v1",
    kind: "setup",
    setup_version_id: 5,
    n: 35,
    wins: 21,
    losses: 14,
    breakeven: 0,
    counts_only: false,
    counts_only_reason: null,
    includes_imported: false,
    currencies: ["USD"],
    currency: "USD",
    win_rate: 0.6,
    avg_win: 50,
    avg_loss: -50,
    payoff: 1,
    profit_factor: 1.5,
    expectancy: 10,
    expectancy_interval: { low: -4.12, high: 24.5, level: 0.9 },
    n_r: 35,
    expectancy_r: 0.2,
    expectancy_r_interval: { low: -0.08, high: 0.49, level: 0.9 },
    r_note: null,
    adherence_rate: 0.5,
    adherence_n: 20,
    avg_holding_days: 2,
    total_net_pnl: 350,
    money_note: null,
    ...overrides,
  };
}

const COUNTS = group({
  key: "setup:6",
  label: "Pullback v1",
  setup_version_id: 6,
  n: 4,
  wins: 4,
  losses: 0,
  counts_only: true,
  counts_only_reason:
    "Counts only: 4 closed trades, under the 30 needed. Below 30 the average is noise, so no expectancy, interval or rate is shown.",
  win_rate: null,
  expectancy: null,
  expectancy_interval: null,
  expectancy_r: null,
  expectancy_r_interval: null,
  profit_factor: null,
  payoff: null,
  avg_win: null,
  avg_loss: null,
  adherence_rate: null,
  avg_holding_days: null,
  total_net_pnl: null,
});

function stats(overall: EdgeGroup): EdgeStats {
  return {
    book_id: null,
    source: null,
    sources_included: ["paper"],
    setup_version_id: null,
    tag: null,
    date_from: null,
    date_to: null,
    min_closed: 30,
    seed: 20261126,
    resamples: 5000,
    mean_block: 3,
    interval_level: 0.9,
    method: "90% stationary bootstrap interval.",
    open_excluded: 0,
    overall,
    by_setup: [overall],
    by_setup_tag: [],
    by_mistake_tag: [],
    by_source: [],
    drift: [],
    imported_fees_estimated: false,
    honesty: ["These are your recorded trades only.", "Not advice."],
  };
}

function drift(overrides: Partial<EdgeDrift> = {}): EdgeDrift {
  return {
    setup_version_id: 5,
    label: "Breakout v1",
    status: "consistent",
    text: "The backtest's expectancy lies inside your live 90% interval.",
    live_n: 35,
    live_n_r: 35,
    live_expectancy_r: 0.2,
    live_interval: { low: -0.08, high: 0.49, level: 0.9 },
    live_win_rate: 0.6,
    live_avg_holding_days: 2,
    backtest: {
      run_id: 12,
      created_at: "2026-11-20T10:00:00",
      ticker: "AAPL",
      closed_trades: 40,
      n_r: 40,
      expectancy_r: 0.25,
      win_rate: 0.5,
      avg_holding_days: 4,
      report_expectancy_r: 0.25,
      holdout: "last_20pct",
      sample: "in_sample",
      sample_note: "In-sample: the first 80% of the range. The holdout is still locked.",
      unlocked_at: null,
    },
    diff_expectancy_r: -0.05,
    diff_win_rate: 0.1,
    diff_avg_holding_days: -2,
    ...overrides,
  };
}

describe("journal edge helpers", () => {
  it("formats intervals and shares", () => {
    expect(pct(0.6)).toBe("60.0%");
    expect(pct(null)).toBe("—");
    expect(rInterval({ low: -0.0026, high: 0.3394, level: 0.9 })).toBe("0.00R to +0.34R");
    expect(rInterval({ low: -0.08, high: 0.49, level: 0.9 })).toBe("-0.08R to +0.49R");
    expect(moneyInterval({ low: -4.12, high: 24.5, level: 0.9 }, "USD")).toBe("-$4.12 to $24.50");
    expect(moneyInterval({ low: 1, high: 2, level: 0.9 }, null)).toBe("—");
  });

  it("builds the page URL and the API query", () => {
    expect(edgeHref(null)).toBe("/portfolio/journal/edge");
    expect(edgeHref(3, { source: "replay", tag: "gap", setupVersionId: 5 })).toBe(
      "/portfolio/journal/edge?book=3&source=replay&tag=gap&setup=5",
    );
    expect(edgeQuery("all", { setupVersionId: 5, from: "2025-01-01" })).toBe(
      "setup_version_id=5&from=2025-01-01",
    );
  });
});

describe("EdgeOverview", () => {
  it("shows counts only under 30, with the reason and no figures", () => {
    render(<EdgeOverview stats={stats(COUNTS)} />);
    const box = screen.getByTestId("edge-overall");
    expect(box).toHaveAttribute("data-counts-only", "true");
    expect(box).toHaveTextContent("4 closed trades (4 won, 0 lost)");
    expect(screen.getByTestId("edge-counts-only")).toHaveTextContent("under the 30 needed");
    expect(screen.queryByTestId("edge-expectancy")).toBeNull();
    expect(screen.queryByText(/90%/)).toBeNull();
  });

  it("shows the figures and the interval at 30 or more", () => {
    render(<EdgeOverview stats={stats(group())} />);
    expect(screen.getByTestId("edge-overall")).toHaveAttribute("data-counts-only", "false");
    expect(screen.getByTestId("edge-expectancy")).toHaveTextContent("$10.00");
    expect(screen.getByTestId("edge-expectancy-r")).toHaveTextContent("+0.20R");
    expect(screen.getByText("90%: -0.08R to +0.49R")).toBeInTheDocument();
    expect(screen.getByText("90%: -$4.12 to $24.50")).toBeInTheDocument();
  });
});

describe("EdgeGroupsTable", () => {
  it("renders a counts-only row beside a full one", () => {
    render(<EdgeGroupsTable groups={[group(), COUNTS]} caption="By setup" />);
    const rows = screen.getAllByTestId("edge-group-row");
    expect(rows.map((r) => r.getAttribute("data-counts-only"))).toEqual(["false", "true"]);
    expect(within(rows[0]).getByText("-0.08R to +0.49R")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/under the 30 needed/)).toBeInTheDocument();
    expect(within(rows[1]).queryByText(/R to/)).toBeNull();
    const cards = screen.getAllByTestId("edge-group-card");
    expect(cards[1]).toHaveAttribute("data-counts-only", "true");
  });

  it("says when there is nothing to show", () => {
    render(<EdgeGroupsTable groups={[]} caption="By tag" />);
    expect(screen.getByText("No closed trades under these filters.")).toBeInTheDocument();
  });
});

describe("EdgeDriftCard", () => {
  it("compares live with the backtest and says it is in-sample", () => {
    render(<EdgeDriftCard drift={drift()} />);
    const card = screen.getByTestId("edge-drift-card");
    expect(card).toHaveAttribute("data-status", "consistent");
    expect(screen.getByTestId("edge-drift-status")).toHaveTextContent("Consistent");
    expect(card).toHaveTextContent("-0.05R");
    expect(card).toHaveTextContent("+10.0 pts");
    expect(screen.getByTestId("edge-drift-sample")).toHaveTextContent("In-sample");
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/backtest/runs/12",
    );
  });

  it("names the other states", () => {
    const { rerender } = render(
      <EdgeDriftCard drift={drift({ status: "outside_interval", text: "Outside." })} />,
    );
    expect(screen.getByTestId("edge-drift-status")).toHaveTextContent("Outside the Interval");
    rerender(
      <EdgeDriftCard
        drift={drift({
          status: "too_few_live_trades",
          text: "Too few live trades with R: 26 more needed to compare.",
          live_n_r: 4,
          live_interval: null,
          diff_expectancy_r: null,
        })}
      />,
    );
    expect(screen.getByTestId("edge-drift-status")).toHaveTextContent("Too Few Live Trades");
    expect(screen.getByText(/26 more needed/)).toBeInTheDocument();
    rerender(
      <EdgeDriftCard
        drift={drift({
          status: "no_backtest",
          text: "No backtest for this setup.",
          backtest: null,
        })}
      />,
    );
    expect(screen.getByTestId("edge-drift-status")).toHaveTextContent("No Backtest");
    expect(screen.getByText("No backtest for this setup.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open the run" })).toBeNull();
  });
});

describe("EdgeHonesty", () => {
  it("lists every note", () => {
    render(<EdgeHonesty notes={["Not advice.", "Small samples are noise."]} />);
    expect(screen.getByTestId("edge-honesty")).toHaveTextContent("Small samples are noise.");
  });
});
