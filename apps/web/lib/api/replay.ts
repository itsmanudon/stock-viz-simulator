import "server-only";

import type {
  Drawing,
  DrawingKind,
  DrawingPoint,
  DrawingStyle,
  DrawingsResponse,
} from "@/lib/drawings/kinds";

import { toApiPoints } from "./drawings";
import { authedDelete, authedGet, authedPatch, authedPost, authedPut } from "./server";
import type { Indicators } from "./types";

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
  /** A4.6: the book's currency (the symbol's). */
  currency: string;
  /** A6.9: the session's bars ("1d", or "1m"/"5m"/"15m"/"60m" from stored minutes). */
  interval: string;
  profile_name: string;
};

export type ReplayPosition = {
  ticker: string;
  quantity: string;
  avg_cost: string;
};

export type ReplaySession = ReplaySessionList & {
  model_version: string;
  completed_at: string | null;
  updated_at: string;
  positions: ReplayPosition[];
  fee_schedule: string;
  lag_override: boolean;
  /** False for an index session: watch, draw and study, no orders. */
  tradable: boolean;
  open_orders: number;
  /** A6.9: the minute feed of an intraday session (null for daily). */
  feed?: string | null;
  /** A6.9: the session profile's assumptions, from the API's profile registry. */
  profile_assumptions?: string[];
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
  /** A4.6: fees in the session currency ("0" on USD and before A4.6). */
  fees: string;
  fee_lines: Array<{ key: string; label: string; amount: string; rate: string }>;
  order_id: number | null;
};

export type ReplayOrderType = "limit" | "stop_loss" | "take_profit";

export type ReplayOrder = {
  id: number;
  session_id: number;
  ticker: string;
  side: "buy" | "sell";
  /** A6.9: "bracket" is a bracket's entry; its stop and target carry `parent_id`. */
  order_type: ReplayOrderType | "bracket";
  quantity: string;
  limit_price: string;
  /** A6.9: "pending" is a bracket child waiting for its entry to fill. */
  status: "pending" | "open" | "filled" | "cancelled" | "rejected" | "expired";
  placed_at: string;
  resolved_at: string | null;
  reason: string | null;
  parent_id?: number | null;
  /** The entry's id, shared by the entry, its stop and its target. */
  oco_group?: number | null;
  /** The stop filled first because the stop and target were both inside one bar. */
  order_inside_bar_unknown?: boolean;
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
  /** Null for a resting order, which the kernel judges from the next bar. */
  decision: ReplayDecision | null;
  fill: ReplayFill | null;
  order: ReplayOrder | null;
  /** A6.9: a bracket's stop and target (`order` is its entry). */
  children?: ReplayOrder[];
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
  currency: string;
  fees_paid: string;
};

export type ReplayAvailability = {
  ticker: string;
  currency: string;
  first_bar: string;
  last_bar: string;
  bars_count: number;
  lag_days: number;
  /** The last end date the 30-day lag allows (null: no lag or waived). */
  max_end: string | null;
  lag_waived: boolean;
  default_starting_cash: string;
  fee_schedule: string;
  tradable: boolean;
  /** A6.9: "1d" plus the intraday intervals when minutes are stored. */
  intervals?: string[];
  minute_feed?: string | null;
  minute_first?: string | null;
  minute_last?: string | null;
};

export type ReplayInterval = "1d" | "1m" | "5m" | "15m" | "60m";
export type ReplayProfileName = "legacy_close" | "intrabar_ohlc";

export type ReplayCreateInput = {
  ticker: string;
  start_at: string;
  end_at?: string | null;
  starting_cash?: string;
  interval?: ReplayInterval;
  profile?: ReplayProfileName;
};

export type ReplayOrderInput = {
  side: "buy" | "sell";
  order_type?: "market" | ReplayOrderType | "bracket";
  quantity: string;
  /** The limit or trigger price; required for a resting order (and a limit bracket entry). */
  limit_price?: string;
  /** A6.9: a bracket's entry, stop and target. */
  entry_type?: "market" | "limit";
  stop_price?: string;
  target_price?: string;
  /** 27 Nov 2026: a short bracket (US listings) sells short; its side is sell. */
  direction?: "long" | "short";
};

/** The JSON body of an order (shared with the drill routes). */
export function replayOrderBody(body: ReplayOrderInput): Record<string, string | undefined> {
  const orderType = body.order_type ?? "market";
  if (orderType === "bracket") {
    const entry = body.entry_type ?? "market";
    const short = body.direction === "short";
    return {
      side: short ? "sell" : "buy",
      order_type: "bracket",
      direction: short ? "short" : "long",
      quantity: body.quantity,
      entry_type: entry,
      stop_price: body.stop_price,
      target_price: body.target_price,
      ...(entry === "limit" ? { limit_price: body.limit_price } : {}),
    };
  }
  return {
    side: body.side,
    order_type: orderType,
    quantity: body.quantity,
    ...(orderType === "market" ? {} : { limit_price: body.limit_price }),
  };
}

export type ReplayEpisodeFill = Omit<ReplayFill, "fee_lines" | "order_id"> & {
  equity_after: string | null;
  concentration_pct: string | null;
};

export type ReplayEpisodeForensics = {
  index: number;
  ticker: string;
  opened_at: string;
  closed_at: string | null;
  status: "open" | "closed";
  entry_price: string;
  exit_price: string | null;
  entry_quantity: string;
  peak_quantity: string;
  weighted_entry_price: string;
  weighted_exit_price: string | null;
  realized_pnl: string;
  unrealized_pnl: string | null;
  return_pct: string | null;
  holding_bars: number;
  holding_calendar_days: number;
  mae_amount: string | null;
  mae_pct: string | null;
  mfe_amount: string | null;
  mfe_pct: string | null;
  benchmark_return_pct: string | null;
  excess_return_pct: string | null;
  max_position_pct: string | null;
  entry_equity: string | null;
  peak_exposure: string;
  fills: ReplayEpisodeFill[];
  /** A4.6: the episode's fees; realized_pnl is net of them. */
  fees: string;
  /** 27 Nov 2026: "short" when a short sale opened the episode. */
  side: "long" | "short";
};

export type ReplayForensics = {
  ticker: string;
  status: string;
  analysis_scope: "so_far" | "final" | "cancelled";
  analysis_at: string;
  starting_cash: string;
  equity: string;
  replay_return_pct: string;
  buy_hold_return_pct: string | null;
  excess_return_pct: string | null;
  max_drawdown_pct: string | null;
  max_concentration_pct: string | null;
  fills_count: number;
  episodes_count: number;
  closed_episodes_count: number;
  open_episodes_count: number;
  episodes: ReplayEpisodeForensics[];
  currency: string;
};

export type ReplayJournal = {
  session_id: number;
  thesis: string | null;
  invalidation: string | null;
  expected_holding_bars: number | null;
  confidence: number | null;
  reflection: string | null;
  locked: boolean;
  locked_at: string | null;
  /** A5.4: the journal was started after the first fill (never "locked"). */
  written_after_entry: boolean;
  created_at: string;
  updated_at: string;
};

export type ReplayJournalInput = {
  thesis?: string | null;
  invalidation?: string | null;
  expected_holding_bars?: number | null;
  confidence?: number | null;
  reflection?: string | null;
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

/**
 * Advance from the bar on screen. A repeat after the session has moved on
 * changes nothing (audit SR-10). From the last bar, this completes the session.
 */
export function advanceReplaySession(
  sessionId: number,
  expectedCurrentAt?: string,
): Promise<ReplaySession> {
  const qs = expectedCurrentAt
    ? `?expected_current_at=${encodeURIComponent(expectedCurrentAt)}`
    : "";
  return authedPost(`/v1/replay/sessions/${sessionId}/advance${qs}`);
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
  return authedPost(`/v1/replay/sessions/${sessionId}/orders`, replayOrderBody(body));
}

/** A4.6: the session's resting orders (every status), oldest first. */
export function getReplayOrders(sessionId: number): Promise<ReplayOrder[]> {
  return authedGet(`/v1/replay/sessions/${sessionId}/orders`);
}

export function cancelReplayOrder(sessionId: number, orderId: number): Promise<ReplayOrder> {
  return authedPost(`/v1/replay/sessions/${sessionId}/orders/${orderId}/cancel`);
}

/**
 * A4.6: indicators computed by the API from the session's bars up to its
 * clock (warm-up from earlier stored bars). Never the public indicators route.
 */
export function getReplayIndicators(sessionId: number, names: string[]): Promise<Indicators> {
  const q = new URLSearchParams({ names: names.join(",") });
  return authedGet(`/v1/replay/sessions/${sessionId}/indicators?${q.toString()}`);
}

export type ReplayNewsEvent = {
  type: "news";
  date: string;
  count: number;
  sources: string[];
  headlines: Array<{
    id: string;
    title: string;
    source: string | null;
    url: string | null;
    available_at: string;
    published_at: string | null;
  }>;
};

export type ReplayFillEvent = {
  type: "fill";
  date: string;
  ts: string;
  side: string;
  quantity: string;
  price: string;
  r_multiple: number | null;
};

export type ReplayEvents = {
  session_id: number;
  ticker: string;
  current_at: string;
  news_rule: string;
  events: Array<ReplayNewsEvent | ReplayFillEvent>;
};

/** A4.6: news known by the replay clock and the session's fills. */
export function getReplayEvents(sessionId: number): Promise<ReplayEvents> {
  return authedGet(`/v1/replay/sessions/${sessionId}/events`);
}

/** A4.6: drawings made inside this session only. */
export function listReplayDrawings(sessionId: number): Promise<DrawingsResponse> {
  return authedGet(`/v1/replay/sessions/${sessionId}/drawings`);
}

export type ReplayDrawingInput = {
  kind: DrawingKind;
  points: DrawingPoint[];
  style?: DrawingStyle;
  label?: string | null;
  locked?: boolean;
};

export function createReplayDrawing(
  sessionId: number,
  input: ReplayDrawingInput,
): Promise<Drawing> {
  return authedPost(`/v1/replay/sessions/${sessionId}/drawings`, {
    ...input,
    points: toApiPoints(input.points),
  });
}

export function updateReplayDrawing(
  sessionId: number,
  id: number,
  changes: Partial<Omit<ReplayDrawingInput, "kind">>,
): Promise<Drawing> {
  const body = changes.points ? { ...changes, points: toApiPoints(changes.points) } : changes;
  return authedPatch(`/v1/replay/sessions/${sessionId}/drawings/${id}`, body);
}

export function deleteReplayDrawing(sessionId: number, id: number): Promise<void> {
  return authedDelete(`/v1/replay/sessions/${sessionId}/drawings/${id}`);
}

export function getReplayAvailability(ticker: string): Promise<ReplayAvailability> {
  const q = new URLSearchParams({ ticker });
  return authedGet(`/v1/replay/availability?${q.toString()}`);
}

export function getReplayForensics(sessionId: number): Promise<ReplayForensics> {
  return authedGet(`/v1/replay/sessions/${sessionId}/forensics`);
}

export function getReplayJournal(sessionId: number): Promise<ReplayJournal> {
  return authedGet(`/v1/replay/sessions/${sessionId}/journal`);
}

export function putReplayJournal(
  sessionId: number,
  body: ReplayJournalInput,
): Promise<ReplayJournal> {
  return authedPut(`/v1/replay/sessions/${sessionId}/journal`, body);
}
