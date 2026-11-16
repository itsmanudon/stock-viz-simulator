import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImpliedVolatility, OptionQuote, OptionQuoteRequest } from "@/lib/api/option-quote";

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  openOptionAction: vi.fn(),
}));

const getOptionQuote = vi.fn<(request: OptionQuoteRequest) => Promise<OptionQuote>>();
const getImpliedVolatility = vi.fn<(request: { price: string }) => Promise<ImpliedVolatility>>();
vi.mock("@/lib/api/option-quote", () => ({
  getOptionQuote: (request: OptionQuoteRequest) => getOptionQuote(request),
  getImpliedVolatility: (request: { price: string }) => getImpliedVolatility(request),
}));

const { ApiError } = await import("@/lib/api/client");
const { OptionTradeForm } = await import("@/components/option-trade-form");

const SYMBOLS = [
  { ticker: "AAPL", name: "Apple" },
  { ticker: "MSFT", name: "Microsoft" },
];

function quoteFor(request: OptionQuoteRequest): OptionQuote {
  const spot = request.ticker === "AAPL" ? "188.38" : "410.10";
  return {
    ticker: request.ticker,
    option_type: request.option_type,
    strike: request.strike ?? spot,
    expiry: request.expiry,
    quantity: request.quantity,
    spot,
    spot_at: "2026-11-06T00:00:00",
    volatility: 0.2514,
    risk_free_rate: 0.05,
    per_share: "7.125",
    premium: (7.125 * 100 * request.quantity).toFixed(2),
    contract_size: 100,
    greeks: { delta: 0.5, gamma: 0.01, theta: -0.02, vega: 0.3, rho: 0.12 },
    volatility_method: "historical volatility of daily closes, 30 sessions, annualised",
    volatility_closes: 31,
    premium_floor_applied: false,
  };
}

describe("option ticket", () => {
  beforeEach(() => {
    getOptionQuote.mockReset().mockImplementation(async (request) => quoteFor(request));
  });

  it("posts a key the API accepts once the form is in the browser (audit LG-10)", () => {
    const { container } = render(<OptionTradeForm options={SYMBOLS} />);

    const key = container.querySelector<HTMLInputElement>('input[name="client_order_id"]');
    expect(key?.value).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it("shows the premium the buy takes before it is placed (audit LG-7)", async () => {
    render(<OptionTradeForm options={SYMBOLS} />);

    const quote = await screen.findByRole("region", { name: "Option quote" });
    await waitFor(() => expect(quote).toHaveTextContent("$712.50 for 1 × 100 shares"));
    expect(quote).toHaveTextContent("$188.38 · close of Nov 6, 2026");
    expect(quote).toHaveTextContent("25.1%");
    expect(screen.getByRole("button", { name: "Buy call for $712.50" })).toBeVisible();
  });

  it("starts the strike at the money and follows the symbol until edited", async () => {
    render(<OptionTradeForm options={SYMBOLS} />);
    const strike = screen.getByLabelText("Strike") as HTMLInputElement;

    await waitFor(() => expect(strike.value).toBe("188.38"));
    expect(getOptionQuote.mock.calls[0]?.[0].strike).toBeUndefined();

    fireEvent.change(screen.getByLabelText("Underlying"), { target: { value: "MSFT" } });
    await waitFor(() => expect(strike.value).toBe("410.10"));

    fireEvent.change(strike, { target: { value: "400" } });
    fireEvent.change(screen.getByLabelText("Underlying"), { target: { value: "AAPL" } });
    await waitFor(() =>
      expect(getOptionQuote).toHaveBeenLastCalledWith(
        expect.objectContaining({ ticker: "AAPL", strike: "400" }),
      ),
    );
    expect(strike.value).toBe("400");
  });

  it("says why a contract cannot be priced", async () => {
    getOptionQuote.mockRejectedValue(
      new ApiError(
        422,
        "/v1/options/quote",
        '{"detail":"No market data for \'AAPL\'; cannot price option"}',
      ),
    );
    render(<OptionTradeForm options={SYMBOLS} />);

    expect(await screen.findByText("No market data for 'AAPL'; cannot price option")).toBeVisible();
  });

  it("shows the Greeks with what they mean for one contract (Phase 9.1, UX-5)", async () => {
    render(<OptionTradeForm options={SYMBOLS} />);

    const list = await screen.findByLabelText("Greeks");
    expect(list).toHaveTextContent("Delta");
    expect(list).toHaveTextContent("moves like 50 shares per contract");
    expect(list).toHaveTextContent("-$2.00 per contract");
    expect(list).toHaveTextContent("Rho");
    expect(screen.getByRole("region", { name: "Option quote" })).toHaveTextContent("5.0%");
  });

  it("says when the premium is the 1-cent minimum (LG-14)", async () => {
    getOptionQuote.mockImplementation(async (request) => ({
      ...quoteFor(request),
      per_share: "0.01",
      premium: "1.00",
      premium_floor_applied: true,
    }));
    render(<OptionTradeForm options={SYMBOLS} />);

    expect(await screen.findByText(/premium is the 1-cent minimum/)).toBeVisible();
  });

  it("solves the volatility a premium implies, without changing the buy", async () => {
    getImpliedVolatility.mockResolvedValue({
      ticker: "AAPL",
      strike: "188.38",
      expiry: "2026-12-16",
      per_share_price: "9.00",
      implied_volatility: 0.3312,
      reason: null,
      historical_volatility: 0.2514,
    });
    render(<OptionTradeForm options={SYMBOLS} />);
    await screen.findByLabelText("Greeks");

    fireEvent.change(screen.getByLabelText("Premium per share (USD)"), {
      target: { value: "9.00" },
    });

    const result = await screen.findByLabelText("Implied volatility");
    expect(result).toHaveTextContent("Implies 33.1% a year, against 25.1% historical");
    expect(getImpliedVolatility).toHaveBeenLastCalledWith(
      expect.objectContaining({ price: "9.00", ticker: "AAPL" }),
    );
    expect(screen.getByRole("button", { name: "Buy call for $712.50" })).toBeVisible();
  });
});
