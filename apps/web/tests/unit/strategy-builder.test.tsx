import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OptionQuote } from "@/lib/api/option-quote";
import type { StrategyPayoff, StrategyRequest } from "@/lib/api/option-strategies";

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  openStrategyAction: vi.fn(),
}));

const getOptionQuote = vi.fn<() => Promise<OptionQuote>>();
vi.mock("@/lib/api/option-quote", () => ({
  getOptionQuote: () => getOptionQuote(),
  getOptionSurface: () =>
    Promise.resolve({ ticker: "AAPL", snapshot_date: null, spot: null, expiries: [], source: "" }),
}));

const getStrategyPayoff = vi.fn<(r: StrategyRequest) => Promise<StrategyPayoff>>();
vi.mock("@/lib/api/option-strategies", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/option-strategies")>();
  return { ...real, getStrategyPayoff: (r: StrategyRequest) => getStrategyPayoff(r) };
});

const { StrategyBuilder } = await import("@/components/strategy-builder");
const { defaultStrikes } = await import("@/lib/api/option-strategies");

function payoffFor(r: StrategyRequest): StrategyPayoff {
  return {
    quote: {
      kind: r.kind,
      label: r.kind === "bull_call" ? "Bull call spread" : "Iron condor",
      ticker: r.ticker,
      quantity: r.quantity,
      spot: "187.40",
      spot_at: "2026-11-13T00:00:00",
      legs: r.strikes.map((k, i) => ({
        side: i === 0 ? "long" : "short",
        option_type: "call",
        strike: k,
        expiry: r.expiry,
        per_share: i === 0 ? "6.00" : "2.00",
        premium: i === 0 ? "600.00" : "200.00",
      })),
      risk: {
        net_premium: "-400.00",
        collateral: "0.00",
        shares_reserved: "0",
        max_loss: "400.00",
        max_gain: "600.00",
        breakevens: ["189.00"],
        basis: "bull call spread at expiry",
      },
    },
    horizon: r.expiry,
    points: [
      { spot: 150, at_expiry: -400, today: -380 },
      { spot: 185, at_expiry: -400, today: -100 },
      { spot: 195, at_expiry: 600, today: 300 },
      { spot: 230, at_expiry: 600, today: 590 },
    ],
    prob_profit: 0.43,
    volatility: 0.25,
    method: "profit or loss after premiums",
  };
}

describe("strategy builder", () => {
  beforeEach(() => {
    getOptionQuote.mockReset().mockResolvedValue({ spot: "187.40" } as OptionQuote);
    getStrategyPayoff.mockReset().mockImplementation(async (r) => payoffFor(r));
  });

  it("starts the strikes around today's close and prices the strategy", async () => {
    render(<StrategyBuilder options={[{ ticker: "AAPL", name: "Apple" }]} />);

    await waitFor(() => expect(getStrategyPayoff).toHaveBeenCalled());
    expect(getStrategyPayoff).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "bull_call", ticker: "AAPL", strikes: ["185", "195"] }),
    );
    const figures = await screen.findByRole("region", { name: "Strategy figures" });
    expect(figures).toHaveTextContent("Net premium paid$400.00");
    expect(figures).toHaveTextContent("Most it can lose$400.00");
    expect(figures).toHaveTextContent("Breakevens at expiry$189.00");
    expect(figures).toHaveTextContent("Chance of profit (model)43%");
    expect(within(figures).getByRole("img", { name: /Profit or loss by price/ })).toBeVisible();
  });

  it("places only after a review, as one strategy", async () => {
    const { container } = render(<StrategyBuilder options={[{ ticker: "AAPL", name: "Apple" }]} />);
    await screen.findByRole("region", { name: "Strategy figures" });
    const step = () =>
      container.querySelector<HTMLInputElement>('input[name="review_step"]')?.value;
    expect(step()).toBe("draft");

    fireEvent.click(screen.getByRole("button", { name: "Review strategy" }));

    const review = screen.getByRole("group", { name: "Strategy review" });
    expect(review).toHaveTextContent("Opens 2 legs together at these prices, or none");
    expect(step()).toBe("confirmed");
    expect(screen.getByRole("button", { name: "Place bull call spread" })).toBeVisible();
    expect(container.querySelector('input[name="client_order_id"]')).not.toBeNull();
  });

  it("asks for four strikes for an iron condor", async () => {
    render(<StrategyBuilder options={[{ ticker: "AAPL", name: "Apple" }]} />);
    await screen.findByRole("region", { name: "Strategy figures" });

    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "iron_condor" } });

    await waitFor(() =>
      expect(getStrategyPayoff).toHaveBeenLastCalledWith(
        expect.objectContaining({ kind: "iron_condor", strikes: ["170", "180", "190", "200"] }),
      ),
    );
    for (const label of ["Buy put", "Write put", "Write call", "Buy call"]) {
      expect(screen.getByLabelText(label)).toBeVisible();
    }
  });

  it("chooses strike steps that suit the price", () => {
    expect(defaultStrikes("bull_call", 23.4)).toEqual(["23", "25"]);
    expect(defaultStrikes("straddle", 412)).toEqual(["410"]);
    expect(defaultStrikes("cash_secured_put", 104)).toEqual(["100"]);
  });
});
