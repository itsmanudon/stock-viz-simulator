import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AutoplayStep } from "@/app/(product)/(authed)/replay/actions";
import { ReplayAutoplay } from "@/components/replay-autoplay";
import { ORDER_UNKNOWN_BADGE, ReplayOrders } from "@/components/replay-orders";
import { ReplayTradeTicket, bracketLevelsProblem } from "@/components/replay-trade-ticket";
import type { ReplayOrder } from "@/lib/api/replay";
import {
  autoplayDelayMs,
  formatReplayClock,
  groupReplayOrders,
  replayErrorMessage,
  replayProfileLabel,
  speedForKey,
  stepSpeed,
} from "@/lib/replay";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));
vi.mock("@/app/(product)/(authed)/replay/actions", () => ({
  submitReplayOrderAction: vi.fn(async () => ({})),
  cancelReplayOrderAction: vi.fn(async () => ({})),
  autoplayStepAction: vi.fn(async () => ({})),
}));

const DAY = 86_400_000;
const day = (n: number) => new Date(Date.UTC(2024, 5, 3) + n * DAY).toISOString();

/** A fake API: each step from the bar it names moves one bar; any other bar is stale. */
function fakeApi(lastBar = 50, delayMs = 5) {
  const state = { current: 0, calls: [] as string[], inFlight: 0, maxInFlight: 0, moves: 0 };
  const step = vi.fn(async (_id: number, from: string): Promise<AutoplayStep> => {
    state.inFlight += 1;
    state.maxInFlight = Math.max(state.maxInFlight, state.inFlight);
    state.calls.push(from);
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    state.inFlight -= 1;
    if (from === day(state.current) && state.current < lastBar) {
      state.current += 1;
      state.moves += 1;
    }
    return { to: day(state.current), status: "active", hasNext: state.current < lastBar };
  });
  return { state, step };
}

describe("A6.9 autoplay", () => {
  it("never double-advances at 10 bars a second", async () => {
    const { state, step } = fakeApi();
    render(<ReplayAutoplay sessionId={1} currentAt={day(0)} hasNext step={step} />);
    fireEvent.keyDown(window, { key: "4" });
    const player = screen.getByTestId("replay-autoplay");
    expect(player).toHaveAttribute("data-speed", "10");
    fireEvent.click(screen.getByRole("button", { name: /Play/ }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 650));
    });
    fireEvent.click(screen.getByRole("button", { name: /Pause/ }));
    await waitFor(() => expect(player).toHaveAttribute("data-playing", "false"));
    // One call at a time, each from the bar the previous answer named, so
    // every call moved exactly one bar.
    expect(state.maxInFlight).toBe(1);
    expect(state.calls.length).toBeGreaterThanOrEqual(4);
    expect(state.calls.length).toBeLessThanOrEqual(8); // at most 10 a second
    expect(state.calls).toEqual(state.calls.map((_, i) => day(i)));
    expect(state.moves).toBe(state.calls.length);
    expect(Number(player.getAttribute("data-advances"))).toBe(state.moves);
    expect(refresh).toHaveBeenCalled();
  });

  it("keeps the speed as a ceiling: 1 bar a second waits between steps", async () => {
    const { state, step } = fakeApi();
    render(<ReplayAutoplay sessionId={1} currentAt={day(0)} hasNext step={step} />);
    fireEvent.click(screen.getByRole("button", { name: /Play/ }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    fireEvent.keyDown(window, { key: " " });
    expect(state.calls.length).toBe(1);
  });

  it("waits out the per-user limit, then carries on, and stops on the last bar", async () => {
    let refused = false;
    const calls: string[] = [];
    const step = vi.fn(async (_id: number, from: string): Promise<AutoplayStep> => {
      calls.push(from);
      if (!refused) {
        refused = true;
        return { to: from, retryAfterMs: 20 };
      }
      return { to: day(1), status: "active", hasNext: false };
    });
    render(<ReplayAutoplay sessionId={1} currentAt={day(0)} hasNext step={step} />);
    fireEvent.click(screen.getByRole("button", { name: /Play/ }));
    const player = screen.getByTestId("replay-autoplay");
    await waitFor(() => expect(player).toHaveAttribute("data-advances", "1"));
    await waitFor(() => expect(player).toHaveAttribute("data-playing", "false"));
    expect(calls).toEqual([day(0), day(0)]);
    expect(screen.getByRole("button", { name: /Play/ })).toBeDisabled();
    expect(screen.getByText(/finishing the replay stays your click/)).toBeVisible();
  });

  it("steps with the arrow key, pauses on an error and ignores keys in fields", async () => {
    const step = vi.fn(
      async (): Promise<AutoplayStep> => ({ error: "This replay is no longer active." }),
    );
    render(
      <>
        <input aria-label="Quantity" />
        <ReplayAutoplay sessionId={1} currentAt={day(0)} hasNext step={step} />
      </>,
    );
    fireEvent.keyDown(screen.getByLabelText("Quantity"), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByLabelText("Quantity"), { key: "3" });
    expect(step).not.toHaveBeenCalled();
    expect(screen.getByTestId("replay-autoplay")).toHaveAttribute("data-speed", "1");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("no longer active"));
    fireEvent.keyDown(window, { key: "ArrowUp" });
    expect(screen.getByTestId("replay-autoplay")).toHaveAttribute("data-speed", "2");
    fireEvent.keyDown(window, { key: "ArrowDown" });
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(screen.getByTestId("replay-autoplay")).toHaveAttribute("data-speed", "1");
  });

  it("maps keys and speeds", () => {
    expect([speedForKey("1"), speedForKey("2"), speedForKey("3"), speedForKey("4")]).toEqual([
      1, 2, 5, 10,
    ]);
    expect(speedForKey("9")).toBeNull();
    expect(stepSpeed(10, 1)).toBe(10);
    expect(stepSpeed(1, -1)).toBe(1);
    expect(stepSpeed(2, 1)).toBe(5);
    expect(autoplayDelayMs(10)).toBe(100);
    expect(replayErrorMessage(429)).toMatch(/Too many steps/);
  });
});

const base: Omit<ReplayOrder, "id" | "order_type" | "side" | "status" | "limit_price"> = {
  session_id: 1,
  ticker: "AAPL",
  quantity: "10",
  placed_at: "2024-06-03T00:00:00Z",
  resolved_at: null,
  reason: null,
  parent_id: null,
  oco_group: null,
};

function order(over: Partial<ReplayOrder> & Pick<ReplayOrder, "id" | "order_type">): ReplayOrder {
  return { side: "sell", status: "open", limit_price: "100", ...base, ...over };
}

describe("A6.9 brackets", () => {
  it("groups a bracket's entry, stop and target into one row", () => {
    const orders = [
      order({ id: 1, order_type: "limit", side: "buy" }),
      order({ id: 2, order_type: "bracket", side: "buy", status: "filled", oco_group: 2 }),
      order({ id: 3, order_type: "stop_loss", parent_id: 2, oco_group: 2, limit_price: "95" }),
      order({ id: 4, order_type: "take_profit", parent_id: 2, oco_group: 2, limit_price: "105" }),
    ];
    const rows = groupReplayOrders(orders);
    expect(rows.map((r) => r.kind)).toEqual(["bracket", "single"]);
    const bracket = rows[0];
    expect(bracket.kind === "bracket" && [bracket.stop?.id, bracket.target?.id]).toEqual([3, 4]);
  });

  it("shows the linked group and labels a stop that filled with the order unknown", () => {
    const orders = [
      order({ id: 2, order_type: "bracket", side: "buy", status: "filled", oco_group: 2 }),
      order({
        id: 3,
        order_type: "stop_loss",
        parent_id: 2,
        oco_group: 2,
        limit_price: "95",
        status: "filled",
        resolved_at: "2024-06-04T00:00:00Z",
        reason: "Order inside the bar unknown: the stop fills first",
        order_inside_bar_unknown: true,
      }),
      order({
        id: 4,
        order_type: "take_profit",
        parent_id: 2,
        oco_group: 2,
        limit_price: "105",
        status: "cancelled",
        resolved_at: "2024-06-04T00:00:00Z",
        reason: "One cancels the other: the stop filled",
      }),
    ];
    render(
      <ReplayOrders
        sessionId={1}
        orders={orders}
        currency="USD"
        readOnly={false}
        profileName="intrabar_ohlc"
      />,
    );
    const group = screen.getByTestId("replay-bracket");
    expect(group).toHaveAttribute("data-oco-group", "2");
    expect(group).toHaveTextContent("Bracket buy 10 AAPL: entry filled at $100.00");
    const legs = within(group).getAllByTestId("replay-bracket-leg");
    expect(legs.map((l) => l.getAttribute("data-leg"))).toEqual(["stop_loss", "take_profit"]);
    expect(within(legs[0]).getByTestId("replay-order-unknown")).toHaveTextContent(
      ORDER_UNKNOWN_BADGE,
    );
    expect(within(legs[1]).queryByTestId("replay-order-unknown")).toBeNull();
    expect(legs[1]).toHaveTextContent("One cancels the other: the stop filled");
    expect(screen.getByText(/judged on each later bar's range/)).toBeVisible();
    expect(screen.queryByTestId("replay-order-cancel")).toBeNull();
  });

  it("says pending children wait for the entry, and offers to cancel it", () => {
    const orders = [
      order({ id: 2, order_type: "bracket", side: "buy", oco_group: 2, limit_price: "98" }),
      order({ id: 3, order_type: "stop_loss", parent_id: 2, status: "pending" }),
      order({ id: 4, order_type: "take_profit", parent_id: 2, status: "pending" }),
    ];
    render(<ReplayOrders sessionId={1} orders={orders} currency="USD" readOnly={false} />);
    expect(screen.getByText("The stop and the target wait for the entry to fill.")).toBeVisible();
    expect(screen.getAllByText("Waiting for entry")).toHaveLength(2);
    expect(screen.getByTestId("replay-bracket")).toHaveTextContent("limit entry at $98.00");
    expect(screen.getAllByTestId("replay-order-cancel")).toHaveLength(3);
  });

  it("offers a short bracket on a US ticket, with the levels swapped", async () => {
    const user = userEvent.setup();
    render(
      <ReplayTradeTicket
        sessionId={1}
        ticker="AAPL"
        currentClose="100"
        cash="100000"
        quantityHeld="0"
        readOnly={false}
        profileName="intrabar_ohlc"
        profileVersion="v1"
      />,
    );
    await user.selectOptions(screen.getByTestId("replay-order-type"), "bracket");
    await user.click(screen.getByRole("button", { name: "Sell" }));
    expect(screen.getByTestId("replay-bracket-stop")).toHaveValue(105);
    expect(screen.getByTestId("replay-bracket-target")).toHaveValue(95);
    expect(screen.getByRole("button", { name: "Place short bracket" })).toBeEnabled();
  });

  it("offers a bracket on the ticket with stop and target, buy only in rupees", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ReplayTradeTicket
        sessionId={1}
        ticker="TCS.NS"
        currentClose="100"
        cash="100000"
        quantityHeld="0"
        readOnly={false}
        currency="INR"
        profileName="intrabar_ohlc"
        profileVersion="v1"
      />,
    );
    expect(screen.getByText(/intrabar_ohlc v1/)).toBeVisible();
    await user.selectOptions(screen.getByTestId("replay-order-type"), "bracket");
    expect(screen.getByRole("button", { name: "Sell" })).toBeDisabled();
    expect(screen.getByTestId("replay-bracket-stop")).toHaveValue(95);
    expect(screen.getByTestId("replay-bracket-target")).toHaveValue(105);
    expect(screen.queryByTestId("replay-limit-price")).toBeNull(); // a market entry
    const hidden = (name: string) =>
      (container.querySelector(`input[name="${name}"]`) as HTMLInputElement | null)?.value;
    expect([hidden("order_type"), hidden("side"), hidden("entry_type")]).toEqual([
      "bracket",
      "buy",
      "market",
    ]);
    expect(screen.getByRole("button", { name: "Place bracket buy" })).toBeEnabled();
    expect(screen.getByText(/the stored minutes decide/)).toBeVisible();
    await user.clear(screen.getByTestId("replay-bracket-stop"));
    await user.type(screen.getByTestId("replay-bracket-stop"), "101");
    expect(screen.getByTestId("replay-bracket-problem")).toHaveTextContent(
      "The stop must be below the entry",
    );
    expect(screen.getByRole("button", { name: "Place bracket buy" })).toBeDisabled();
    await user.selectOptions(screen.getByTestId("replay-bracket-entry"), "limit");
    expect(screen.getByTestId("replay-limit-price")).toBeVisible();
    expect(hidden("entry_type")).toBe("limit");
  });

  it("checks bracket levels as the API does", () => {
    expect(bracketLevelsProblem("100", "95", "105")).toBeNull();
    expect(bracketLevelsProblem("100", "100", "105")).toMatch(/below the entry/);
    expect(bracketLevelsProblem("100", "95", "")).toMatch(/positive stop and target/);
  });

  it("names the profile and an intraday clock", () => {
    expect(replayProfileLabel("intrabar_ohlc", "v1")).toBe("intrabar_ohlc v1");
    expect(replayProfileLabel(null)).toBe("legacy_close v1");
    expect(formatReplayClock("2024-06-04T13:35:00Z", "5m")).toBe("Tue, Jun 4, 2024, 13:35 UTC");
    expect(formatReplayClock("2024-06-04T00:00:00Z", "1d")).toBe("Tuesday, June 4, 2024");
  });
});
