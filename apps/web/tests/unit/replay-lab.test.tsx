import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReplayFillTable } from "@/components/replay-fills";
import { ReplayTradeTicket } from "@/components/replay-trade-ticket";
import type { ReplayFill } from "@/lib/api/replay";

vi.mock("@/app/(product)/(authed)/replay/actions", () => ({
  submitReplayOrderAction: vi.fn(async () => ({})),
  advanceReplayAction: vi.fn(async () => ({})),
  cancelReplayAction: vi.fn(async () => ({})),
}));

const fill: ReplayFill = {
  id: 1,
  session_id: 9,
  ticker: "AAPL",
  side: "buy",
  quantity: "1",
  fill_price: "150",
  realized_pnl: null,
  profile_name: "legacy_close",
  model_version: "v1",
  reference_price: "150",
  reason: "market",
  assumptions: ["Uses stored 1d close"],
  market_interval: "1d",
  order_type: "market",
  evaluated_at: "2024-06-03T00:00:00Z",
  created_at: "2024-06-03T00:00:00Z",
};

describe("Replay Lab presentation", () => {
  it("labels the ticket as a replay market order and omits live paper copy", () => {
    render(
      <ReplayTradeTicket
        sessionId={1}
        ticker="AAPL"
        currentClose="150"
        cash="100000"
        quantityHeld="0"
        readOnly={false}
      />,
    );
    expect(screen.getByText("Replay order")).toBeVisible();
    expect(screen.getByRole("button", { name: /Submit market buy/i })).toBeVisible();
    expect(screen.getByText(/Not live paper trading/i)).toBeVisible();
    expect(screen.queryByRole("heading", { name: /^paper trade$/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sign in to paper trade/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/limit/i)).not.toBeInTheDocument();
  });

  it("exposes fill provenance without future prices", async () => {
    const user = userEvent.setup();
    render(<ReplayFillTable fills={[fill]} />);
    expect(screen.getByRole("table", { name: "Replay fills" })).toHaveTextContent("AAPL");
    expect(screen.getByRole("table", { name: "Replay fills" })).toHaveTextContent(
      "legacy_close v1",
    );
    await user.click(screen.getByText("Why this filled"));
    expect(screen.getByText(/Uses stored 1d close/)).toBeVisible();
    expect(screen.queryByText("1000")).not.toBeInTheDocument();
  });

  it("explains an empty book", () => {
    render(<ReplayFillTable fills={[]} />);
    expect(screen.getByRole("heading", { name: "No replay trades yet." })).toBeVisible();
  });
});
