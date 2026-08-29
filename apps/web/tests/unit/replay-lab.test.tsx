import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReplayAdvanceControls } from "@/components/replay-controls";
import { ReplayFillTable } from "@/components/replay-fills";
import { ReplayForensicsPanel } from "@/components/replay-forensics";
import { ReplayJournalForm } from "@/components/replay-journal";
import { ReplayTradeTicket } from "@/components/replay-trade-ticket";
import type { ReplayFill, ReplayForensics, ReplayJournal } from "@/lib/api/replay";

vi.mock("@/app/(product)/(authed)/replay/actions", () => ({
  submitReplayOrderAction: vi.fn(async () => ({})),
  advanceReplayAction: vi.fn(async () => ({})),
  cancelReplayAction: vi.fn(async () => ({})),
  saveReplayJournalAction: vi.fn(async () => ({})),
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

  it("describes advance as the next stored daily bar, not an exchange calendar", () => {
    render(
      <ReplayAdvanceControls
        sessionId={1}
        currentAt="2020-01-04T00:00:00Z"
        hasNext
        readOnly={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Advance to next session" })).toBeVisible();
    expect(screen.getByText(/Moves to the next stored daily bar/i)).toBeVisible();
    expect(screen.queryByText(/weekends/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/holidays/i)).not.toBeInTheDocument();
  });

  it("renders forensic scorecard, MAE/MFE, and so-far labelling", async () => {
    const user = userEvent.setup();
    const forensics: ReplayForensics = {
      ticker: "AAPL",
      status: "active",
      analysis_scope: "so_far",
      analysis_at: "2020-01-06T00:00:00Z",
      starting_cash: "100000",
      equity: "101000",
      replay_return_pct: "1.0000",
      buy_hold_return_pct: "2.0000",
      excess_return_pct: "-1.0000",
      max_drawdown_pct: "-3.0000",
      max_concentration_pct: "10.0000",
      fills_count: 1,
      episodes_count: 1,
      closed_episodes_count: 0,
      open_episodes_count: 1,
      episodes: [
        {
          index: 1,
          ticker: "AAPL",
          opened_at: "2020-01-04T00:00:00Z",
          closed_at: null,
          status: "open",
          entry_price: "100",
          exit_price: null,
          entry_quantity: "1",
          peak_quantity: "1",
          weighted_entry_price: "100",
          weighted_exit_price: null,
          realized_pnl: "0",
          unrealized_pnl: "5",
          return_pct: "5.0000",
          holding_bars: 2,
          holding_calendar_days: 2,
          mae_amount: "-4",
          mae_pct: "-4.0000",
          mfe_amount: "6",
          mfe_pct: "6.0000",
          benchmark_return_pct: "2.0000",
          excess_return_pct: "3.0000",
          max_position_pct: "10.0000",
          entry_equity: "100000",
          peak_exposure: "100",
          fills: [
            {
              ...fill,
              equity_after: "100000",
              concentration_pct: "10.0000",
            },
          ],
        },
      ],
    };
    render(<ReplayForensicsPanel forensics={forensics} />);
    expect(screen.getByText("So far")).toBeVisible();
    expect(screen.getByText("Buy & hold")).toBeVisible();
    expect(screen.getByText("Excess return")).toBeVisible();
    expect(screen.getByText("Max adverse excursion")).toBeVisible();
    expect(screen.getByText("Max favorable excursion")).toBeVisible();
    expect(screen.getByRole("table", { name: "Replay episodes" })).toHaveTextContent("MAE");
    expect(screen.getByRole("table", { name: "Replay episodes" })).toHaveTextContent("MFE");
    await user.click(screen.getByText("Episode 1 detail"));
    expect(screen.getByText(/legacy_close v1/)).toBeVisible();
  });

  it("locks thesis fields after the first fill and keeps reflection editable", () => {
    const journal: ReplayJournal = {
      session_id: 9,
      thesis: "Buy the dip",
      invalidation: "Close below 90",
      expected_holding_bars: 5,
      confidence: 3,
      reflection: null,
      locked: true,
      locked_at: "2020-01-04T00:00:00Z",
      created_at: "2020-01-04T00:00:00Z",
      updated_at: "2020-01-04T00:00:00Z",
    };
    render(<ReplayJournalForm sessionId={9} journal={journal} hasFills completed={false} />);
    expect(screen.getByLabelText("Thesis")).toHaveAttribute("readOnly");
    expect(screen.getByLabelText("Invalidation")).toHaveAttribute("readOnly");
    expect(screen.getByText(/frozen after the first fill/i)).toBeVisible();
    expect(screen.getByLabelText("Notes")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Save reflection" })).toBeVisible();
  });
});
