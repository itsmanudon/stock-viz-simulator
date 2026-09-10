import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompareInsights, CompareMetricsTable } from "@/components/compare-metrics";
import { CompareSymbolPicker } from "@/components/compare-symbol-picker";
import {
  ResearchEmptyState,
  ResearchPageHeader,
  ResearchSubnav,
} from "@/components/research-page-header";
import type { CompareMetrics } from "@/lib/compare-workspace";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

function metric(overrides: Partial<CompareMetrics> = {}): CompareMetrics {
  return {
    ticker: "AAPL",
    name: "Apple Inc.",
    sector: "Technology",
    color: "#3b82f6",
    bars: [],
    lastPrice: 190,
    returnPct: 12.5,
    volatilityPct: 22.1,
    maxDrawdownPct: 8.4,
    rsi14: 61.2,
    week52PositionPct: 80,
    sentiment7d: 0.2,
    ...overrides,
  };
}

describe("compare presentation", () => {
  it("renders a metrics table with stock workspace links and partial values", () => {
    render(
      <CompareMetricsTable
        rows={[
          metric(),
          metric({
            ticker: "MSFT",
            name: "Microsoft",
            lastPrice: null,
            returnPct: null,
            rsi14: null,
            sentiment7d: null,
          }),
        ]}
      />,
    );

    expect(screen.getByRole("columnheader", { name: "Window return" })).toBeVisible();
    expect(screen.getByRole("link", { name: /AAPL/ })).toHaveAttribute("href", "/stocks/AAPL");
    expect(screen.getByText("+12.50%")).toBeVisible();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("states relative observations without inventing commentary", () => {
    render(
      <CompareInsights insights={[{ id: "leader", text: "AAPL led the window at +12.50%." }]} />,
    );
    expect(screen.getByText("AAPL led the window at +12.50%.")).toBeVisible();
    expect(screen.getByText(/Not commentary/)).toBeVisible();
  });

  it("lets the picker remove a selected symbol via an accessible control", () => {
    render(
      <CompareSymbolPicker
        tickers={["AAPL"]}
        timeframe="1Y"
        names={{ AAPL: "Apple Inc." }}
        search={async () => []}
        list={async () => []}
      />,
    );
    expect(screen.getByRole("button", { name: "Remove AAPL" })).toBeVisible();
  });

  it("offers watchlist symbols as quick-add chips, skipping ones already picked", () => {
    push.mockClear();
    render(
      <CompareSymbolPicker
        tickers={["AAPL"]}
        timeframe="1Y"
        names={{ AAPL: "Apple Inc.", MSFT: "Microsoft" }}
        watchlistTickers={["AAPL", "MSFT"]}
        search={async () => []}
        list={async () => []}
      />,
    );
    // AAPL is already selected, so only MSFT is offered.
    expect(screen.queryByRole("button", { name: "+ AAPL" })).toBeNull();
    screen.getByRole("button", { name: "+ MSFT" }).click();
    expect(push).toHaveBeenCalledWith(expect.stringContaining("AAPL"));
    expect(push).toHaveBeenCalledWith(expect.stringContaining("MSFT"));
  });
});

describe("research chrome", () => {
  it("exposes Compare, Backtest, and Signals in a local research subnav", () => {
    render(
      <>
        <ResearchPageHeader title="Compare" description="How do these assets compare?" />
        <ResearchSubnav current="/compare" />
        <ResearchEmptyState title="Select symbols to compare">
          <p>Add a ticker to begin.</p>
        </ResearchEmptyState>
      </>,
    );

    const nav = screen.getByRole("navigation", { name: "Research tools" });
    expect(within(nav).getByRole("link", { name: "Compare" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Backtest" })).toHaveAttribute(
      "href",
      "/backtest",
    );
    expect(within(nav).getByRole("link", { name: "Signals" })).toHaveAttribute(
      "href",
      "/recommendations",
    );
    expect(screen.getByRole("heading", { name: "Select symbols to compare" })).toBeVisible();
  });
});
