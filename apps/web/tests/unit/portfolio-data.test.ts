import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getDividends,
  getPortfolio,
  getPortfolioAnalytics,
  getPortfolioHistory,
  listOrders,
} from "@/lib/api/trading";
import { loadPortfolioData } from "@/lib/portfolio-data";

vi.mock("@/lib/api/trading", () => ({
  getPortfolio: vi.fn(),
  getPortfolioHistory: vi.fn(),
  getPortfolioAnalytics: vi.fn(),
  getDividends: vi.fn(),
  listOrders: vi.fn(),
}));

const portfolio = {
  portfolio_id: 1,
  display_currency: "USD",
  cash_balance: "100000",
  reserved_cash: "0",
  available_cash: "100000",
  market_value: "0",
  total_value: "100000",
  total_cost_basis: "0",
  unrealized_pl: "0",
  options_market_value: "0",
  positions: [],
  option_positions: [],
};

describe("portfolio server orchestration", () => {
  beforeEach(() => {
    vi.mocked(getPortfolio).mockReset().mockResolvedValue(portfolio);
    vi.mocked(getPortfolioHistory).mockReset().mockResolvedValue([]);
    vi.mocked(getPortfolioAnalytics).mockReset().mockResolvedValue({
      display_currency: "USD",
      history_days: 0,
      total_return_pct: null,
      annualised_return_pct: null,
      sharpe_ratio: null,
      max_drawdown_pct: null,
      risk_free_rate: 0.05,
      sector_allocation: [],
      top_gainers: [],
      top_losers: [],
    });
    vi.mocked(getDividends)
      .mockReset()
      .mockResolvedValue({ ytd_income: "0", history: [], projected: [] });
    vi.mocked(listOrders).mockReset().mockResolvedValue([]);
  });

  it("fetches each Portfolio resource once and maps the selected range", async () => {
    const result = await loadPortfolioData("1y");

    expect(getPortfolio).toHaveBeenCalledTimes(1);
    expect(getPortfolioHistory).toHaveBeenCalledWith(365);
    expect(getPortfolioAnalytics).toHaveBeenCalledTimes(1);
    expect(getDividends).toHaveBeenCalledTimes(1);
    expect(listOrders).toHaveBeenCalledWith("pending");
    expect(result.portfolio).toBe(portfolio);
    expect(result.portfolio.option_positions).toEqual([]);
  });

  it("keeps optional upstream failures distinct from successful empty data", async () => {
    vi.mocked(getPortfolioHistory).mockRejectedValue(new Error("history unavailable"));
    vi.mocked(listOrders).mockRejectedValue(new Error("orders unavailable"));

    const result = await loadPortfolioData("all");

    expect(getPortfolioHistory).toHaveBeenCalledWith(null);
    expect(result.history).toBeNull();
    expect(result.orders).toBeNull();
    expect(result.dividends).toEqual({ ytd_income: "0", history: [], projected: [] });
  });

  it("does not suppress failure of the required portfolio resource", async () => {
    vi.mocked(getPortfolio).mockRejectedValue(new Error("portfolio unavailable"));

    await expect(loadPortfolioData("3m")).rejects.toThrow("portfolio unavailable");
  });
});
