import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const closeOptionFormAction = vi.fn();
vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  closeOptionAction: vi.fn(),
  closeOptionFormAction: (...args: unknown[]) => closeOptionFormAction(...args),
}));

import { CloseOptionButton } from "@/components/close-option-button";
import { PortfolioOptions } from "@/components/portfolio-options";
import type { PortfolioOption } from "@/lib/api/trading";

const option: PortfolioOption = {
  option_id: 8,
  ticker: "AAPL",
  option_type: "call",
  strike: "180",
  expiry: "2999-12-17",
  quantity: 1,
  currency: "USD",
  premium_paid: "420.00",
  market_value_native: "505.25",
  market_value: "505.25",
  unrealized_pl: "85.25",
};

describe("closing an option (audit LG-8)", () => {
  beforeEach(() => closeOptionFormAction.mockReset());

  it("asks before closing and states the amount", async () => {
    closeOptionFormAction.mockResolvedValue({ error: null, closed: true });
    const user = userEvent.setup();
    render(<CloseOptionButton optionId={8} label="AAPL call position" valueText="$505.25" />);

    await user.click(screen.getByRole("button", { name: "Close AAPL call position" }));
    expect(closeOptionFormAction).not.toHaveBeenCalled();
    expect(screen.getByText("Close for about $505.25?")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.queryByText(/Close for about/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close AAPL call position" }));
    await user.click(screen.getByRole("button", { name: "Confirm closing AAPL call position" }));
    expect(closeOptionFormAction).toHaveBeenCalledTimes(1);
  });

  it("shows a refused close instead of the error page", async () => {
    closeOptionFormAction.mockResolvedValue({
      error: "This expired option is awaiting expiry settlement",
      closed: false,
    });
    const user = userEvent.setup();
    render(<CloseOptionButton optionId={8} label="AAPL call position" valueText="$505.25" />);

    await user.click(screen.getByRole("button", { name: "Close AAPL call position" }));
    await user.click(screen.getByRole("button", { name: "Confirm closing AAPL call position" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("awaiting expiry settlement");
  });

  it("offers no close once the contract has expired", () => {
    render(
      <PortfolioOptions positions={[{ ...option, expiry: "2020-01-17" }]} displayCurrency="USD" />,
    );
    const table = screen.getByRole("table", { name: "Options positions" });
    expect(within(table).getByText("Awaiting settlement")).toBeVisible();
    expect(within(table).queryByRole("button", { name: /Close/ })).not.toBeInTheDocument();
  });
});
