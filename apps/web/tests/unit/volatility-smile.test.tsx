import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OptionSurface } from "@/lib/api/option-quote";

const getOptionSurface = vi.fn<(t: string) => Promise<OptionSurface>>();
vi.mock("@/lib/api/option-quote", () => ({
  getOptionSurface: (t: string) => getOptionSurface(t),
}));

const { VolatilitySmile, smilePoints } = await import("@/components/volatility-smile");

const SURFACE: OptionSurface = {
  ticker: "AAPL",
  snapshot_date: "2026-11-13",
  spot: "104",
  expiries: [
    {
      expiry: "2026-12-18",
      points: [
        { strike: "95", call_iv: 0.4, put_iv: 0.33 },
        { strike: "105", call_iv: 0.27, put_iv: 0.29 },
        { strike: "115", call_iv: 0.3, put_iv: null },
      ],
    },
  ],
  source: "yfinance option chains",
};

describe("volatility smile", () => {
  beforeEach(() => getOptionSurface.mockReset());

  it("reads each strike from its out-of-the-money contract", () => {
    // Below today's 104: the put; above: the call.
    expect(smilePoints(SURFACE)[0]?.points).toEqual([
      [95, 0.33],
      [105, 0.27],
      [115, 0.3],
    ]);
  });

  it("draws the stored chain with its date", async () => {
    getOptionSurface.mockResolvedValue(SURFACE);
    render(<VolatilitySmile ticker="AAPL" />);
    const figure = await screen.findByRole("figure", { name: "Volatility smile for AAPL" });
    expect(figure).toHaveTextContent("from the 2026-11-13 chain: 2026-12-18");
    expect(figure).toHaveTextContent("27% to 33%");
  });

  it("says when no chain is stored", async () => {
    getOptionSurface.mockResolvedValue({ ...SURFACE, snapshot_date: null, expiries: [] });
    render(<VolatilitySmile ticker="MSFT" />);
    await waitFor(() =>
      expect(screen.getByText(/No option chain is stored for MSFT yet/)).toBeVisible(),
    );
  });
});
