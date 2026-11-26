import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReplayFillTable } from "@/components/replay-fills";
import { ReplayOrders } from "@/components/replay-orders";
import { ReplayTradeTicket } from "@/components/replay-trade-ticket";
import type { ReplayFill, ReplayOrder } from "@/lib/api/replay";
import { replayCashPresets, replayErrorMessage, replayOrderTypeLabel } from "@/lib/replay";

vi.mock("@/app/(product)/(authed)/replay/actions", () => ({
  submitReplayOrderAction: vi.fn(async () => ({})),
  cancelReplayOrderAction: vi.fn(async () => ({})),
}));
vi.mock("@/app/(product)/(authed)/replay/[sessionId]/drawing-actions", () => ({
  createReplayDrawingAction: vi.fn(),
  updateReplayDrawingAction: vi.fn(),
  deleteReplayDrawingAction: vi.fn(),
}));
vi.mock("@/app/(product)/stocks/[ticker]/drawing-actions", () => ({
  createDrawingAction: vi.fn(),
  updateDrawingAction: vi.fn(),
  deleteDrawingAction: vi.fn(),
}));
vi.mock("@/app/(product)/stocks/[ticker]/avwap-actions", () => ({
  avwapAction: vi.fn(),
  lastEarningsDateAction: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const { REPLAY_DRAWING_KINDS, replayIndicatorsHref } = await import("@/components/replay-chart");

describe("A4.6 replay", () => {
  it("offers every drawing kind but the anchored VWAP", () => {
    expect(REPLAY_DRAWING_KINDS).not.toContain("avwap");
    expect(REPLAY_DRAWING_KINDS).toContain("trendline");
    expect(REPLAY_DRAWING_KINDS).toContain("position_long");
  });

  it("keeps the other params when the indicators change", () => {
    expect(replayIndicatorsHref("/replay/7", "requestedStart=2025-01-01", ["rsi_14"])).toBe(
      "/replay/7?requestedStart=2025-01-01&indicators=rsi_14",
    );
    expect(replayIndicatorsHref("/replay/7", "indicators=rsi_14", [])).toBe("/replay/7");
  });

  it("starts rupee sessions at lakh presets and says why an end is refused", () => {
    expect(replayCashPresets("INR")).toContain("1000000");
    expect(replayCashPresets("GBP")).toContain("100000");
    const lag =
      "Indian replay sessions must end at least 30 days before today: choose an end on or before 2026-10-27";
    expect(replayErrorMessage(400, lag)).toBe(lag);
    expect(replayErrorMessage(400, "No stored 1d bar")).toMatch(/no stored daily bars/);
    expect(replayOrderTypeLabel("stop_loss")).toBe("Stop-loss");
  });

  it("places a limit with a price and makes stops sell-only, in rupees", async () => {
    const user = userEvent.setup();
    render(
      <ReplayTradeTicket
        sessionId={1}
        ticker="TCS.NS"
        currentClose="3500"
        cash="1000000"
        quantityHeld="10"
        readOnly={false}
        currency="INR"
        feeSchedule="in_equity_delivery_nse"
      />,
    );
    expect(screen.getAllByText("₹3,500.00").length).toBeGreaterThan(0);
    expect(screen.getByText(/delivery charges/i)).toBeVisible();
    await user.selectOptions(screen.getByTestId("replay-order-type"), "limit");
    expect(screen.getByLabelText(/Limit price \(INR\)/)).toHaveValue(3500);
    expect(screen.getByRole("button", { name: "Place limit buy" })).toBeEnabled();
    await user.selectOptions(screen.getByTestId("replay-order-type"), "stop_loss");
    expect(screen.getByRole("button", { name: "Buy" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Place stop-loss sell" })).toBeVisible();
    expect(screen.getByLabelText(/Trigger price/)).toBeVisible();
  });

  it("says an index session cannot be traded", () => {
    render(
      <ReplayTradeTicket
        sessionId={1}
        ticker="^NSEI"
        currentClose="22000"
        cash="1000000"
        quantityHeld="0"
        readOnly={false}
        currency="INR"
        tradable={false}
      />,
    );
    expect(screen.getByTestId("replay-not-tradable")).toHaveTextContent("is an index");
    expect(screen.queryByRole("button", { name: /Submit/ })).not.toBeInTheDocument();
  });

  it("lists resting orders with cancel for open ones and fees on fills", () => {
    const orders: ReplayOrder[] = [
      {
        id: 1,
        session_id: 1,
        ticker: "TCS.NS",
        side: "buy",
        order_type: "limit",
        quantity: "5",
        limit_price: "3400",
        status: "open",
        placed_at: "2025-03-03T00:00:00",
        resolved_at: null,
        reason: null,
      },
      {
        id: 2,
        session_id: 1,
        ticker: "TCS.NS",
        side: "sell",
        order_type: "take_profit",
        quantity: "5",
        limit_price: "3900",
        status: "rejected",
        placed_at: "2025-03-03T00:00:00",
        resolved_at: "2025-03-05T00:00:00",
        reason: "Replay position 0 TCS.NS; order requires 5.",
      },
    ];
    render(<ReplayOrders sessionId={1} orders={orders} currency="INR" readOnly={false} />);
    const rows = screen.getAllByTestId("replay-order");
    expect(rows.map((r) => r.dataset.status)).toEqual(["rejected", "open"]);
    expect(screen.getAllByTestId("replay-order-cancel")).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Replay position 0");
    expect(rows[1]).toHaveTextContent("₹3,400.00");

    const fill: ReplayFill = {
      id: 1,
      session_id: 1,
      ticker: "TCS.NS",
      side: "buy",
      quantity: "5",
      fill_price: "3400",
      realized_pnl: null,
      profile_name: "legacy_close",
      model_version: "v1",
      reference_price: "3400",
      reason: "Limit buy",
      assumptions: [],
      market_interval: "1d",
      order_type: "limit",
      evaluated_at: "2025-03-04T00:00:00",
      created_at: "2025-03-04T00:00:00",
      fees: "21.45",
      fee_lines: [{ key: "stt", label: "STT", amount: "17", rate: "0.1% of value" }],
      order_id: 1,
    };
    render(<ReplayFillTable fills={[fill]} currency="INR" />);
    expect(screen.getByTestId("replay-fill-fees")).toHaveTextContent("₹21.45");
  });
});
