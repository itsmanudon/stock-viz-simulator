import "server-only";

import { authedGet, authedPost } from "./server";

export type ReplaySessionList = {
  id: number;
  ticker: string;
  start_at: string;
  current_at: string;
  end_at: string;
  status: string;
  starting_cash: string;
  cash_balance: string;
  has_next: boolean;
  created_at: string;
};

export type ReplayPosition = {
  ticker: string;
  quantity: string;
  avg_cost: string;
};

export type ReplaySession = ReplaySessionList & {
  profile_name: string;
  model_version: string;
  completed_at: string | null;
  updated_at: string;
  positions: ReplayPosition[];
};

export type ReplayBar = {
  ticker: string;
  ts: string;
  interval: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
};

export type ReplayMarket = {
  ticker: string;
  current_at: string;
  start_at: string;
  end_at: string;
  has_next: boolean;
  status: string;
  bar: ReplayBar;
};

export type ReplayFill = {
  id: number;
  session_id: number;
  ticker: string;
  side: string;
  quantity: string;
  fill_price: string;
  realized_pnl: string | null;
  profile_name: string;
  model_version: string;
  reference_price: string | null;
  reason: string;
  assumptions: string[];
  market_interval: string;
  order_type: string;
  evaluated_at: string;
  created_at: string;
};

export type ReplayDecision = {
  status: string;
  fill_quantity: string;
  fill_price: string | null;
  remaining_quantity: string;
  reason: string;
  profile_name: string;
  model_version: string;
  reference_price: string | null;
  assumptions: string[];
};

export type ReplaySubmit = {
  session: ReplaySession;
  decision: ReplayDecision;
  fill: ReplayFill | null;
};

export type ReplaySummary = {
  ticker: string;
  status: string;
  current_at: string;
  current_close: string;
  cash: string;
  starting_cash: string;
  positions_market_value: string;
  equity: string;
  realized_pnl: string;
  unrealized_pnl: string;
  total_pnl: string;
  return_pct: string;
  fills_count: number;
  has_next: boolean;
  visible_high: string;
  visible_low: string;
};

export type ReplayAvailability = {
  ticker: string;
  currency: string;
  first_bar: string;
  last_bar: string;
  bars_count: number;
};

export type ReplayCreateInput = {
  ticker: string;
  start_at: string;
  end_at?: string | null;
  starting_cash?: string;
};

export type ReplayOrderInput = {
  side: "buy" | "sell";
  order_type?: "market";
  quantity: string;
};

export function listReplaySessions(): Promise<ReplaySessionList[]> {
  return authedGet("/v1/replay/sessions");
}

export function getReplaySession(sessionId: number): Promise<ReplaySession> {
  return authedGet(`/v1/replay/sessions/${sessionId}`);
}

export function createReplaySession(body: ReplayCreateInput): Promise<ReplaySession> {
  return authedPost("/v1/replay/sessions", body);
}

export function advanceReplaySession(sessionId: number): Promise<ReplaySession> {
  return authedPost(`/v1/replay/sessions/${sessionId}/advance`);
}

export function cancelReplaySession(sessionId: number): Promise<ReplaySession> {
  return authedPost(`/v1/replay/sessions/${sessionId}/cancel`);
}

export function getReplayMarket(sessionId: number): Promise<ReplayMarket> {
  return authedGet(`/v1/replay/sessions/${sessionId}/market`);
}

export function getReplayHistory(sessionId: number): Promise<ReplayBar[]> {
  return authedGet(`/v1/replay/sessions/${sessionId}/history`);
}

export function getReplaySummary(sessionId: number): Promise<ReplaySummary> {
  return authedGet(`/v1/replay/sessions/${sessionId}/summary`);
}

export function getReplayFills(sessionId: number): Promise<ReplayFill[]> {
  return authedGet(`/v1/replay/sessions/${sessionId}/fills`);
}

export function submitReplayOrder(
  sessionId: number,
  body: ReplayOrderInput,
): Promise<ReplaySubmit> {
  return authedPost(`/v1/replay/sessions/${sessionId}/orders`, {
    side: body.side,
    order_type: body.order_type ?? "market",
    quantity: body.quantity,
  });
}

export function getReplayAvailability(ticker: string): Promise<ReplayAvailability> {
  const q = new URLSearchParams({ ticker });
  return authedGet(`/v1/replay/availability?${q.toString()}`);
}
