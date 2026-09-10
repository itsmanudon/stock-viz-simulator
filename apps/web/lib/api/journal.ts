import "server-only";

import { authedGet } from "./server";

/**
 * Trading Journal reads.
 *
 * Money arrives as decimal strings and stays that way until it is formatted —
 * the same convention the rest of the trading API uses, so a cent is never
 * lost to a float on the way through.
 *
 * Two calls on purpose: the month carries roll-ups only, and per-trade detail
 * is fetched when a day is opened. See `docs/TRADING_JOURNAL.md`.
 */

export type JournalStats = {
  realized_pnl: string;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  gross_profit: string;
  gross_loss: string;
  /** Fraction of *decided* trades that won. Null when none were decided. */
  win_rate: number | null;
  /** Gross profit / gross loss. Null when nothing was lost. */
  profit_factor: number | null;
};

export type JournalDaySummary = {
  /** New York trading-session date, `YYYY-MM-DD`. */
  date: string;
  stats: JournalStats;
};

export type JournalWeekSummary = {
  /** Both bounds are clipped to the month being viewed. */
  start: string;
  end: string;
  stats: JournalStats;
};

export type JournalMonth = {
  period: { year: number; month: number; first_day: string; last_day: string };
  /** Realized P&L is a USD ledger quantity — never the display currency. */
  currency: string;
  summary: JournalStats;
  /** Realized P&L over NAV at the start of the month. Null without a snapshot. */
  return_pct: number | null;
  start_nav: string | null;
  /** Only sessions that had a closing execution. */
  days: JournalDaySummary[];
  weeks: JournalWeekSummary[];
  unavailable_count: number;
};

export type JournalSignal = {
  score: number;
  max_score: number;
  computed_at: string;
};

export type JournalExecution = {
  kind: "equity" | "option";
  /** Trade id for equities, options-position id for options. */
  reference_id: number;
  ticker: string;
  session_date: string;
  executed_at: string;
  realized_pnl: string;
  currency: string;

  side: "buy" | "sell" | null;
  quantity: string | null;
  price: string | null;
  /** Cost basis the realized P&L was measured against. Null on legacy rows. */
  avg_cost: string | null;

  option_type: "call" | "put" | null;
  strike: string | null;
  expiry: string | null;
  contracts: number | null;
  premium_paid: string | null;
  proceeds: string | null;
  option_status: "closed" | "exercised" | "expired" | null;

  /** Reserved for persisted entry provenance; currently null. */
  signal_at_entry: JournalSignal | null;
};

export type JournalDay = {
  date: string;
  currency: string;
  stats: JournalStats;
  executions: JournalExecution[];
  offset: number;
  has_more: boolean;
  unavailable_count: number;
};

export type JournalWeek = JournalWeekSummary & {
  currency: string;
  best_trade: JournalExecution | null;
  worst_trade: JournalExecution | null;
  unavailable_count: number;
};

export function getJournalMonth(year: number, month: number): Promise<JournalMonth> {
  return authedGet<JournalMonth>(`/v1/portfolio/journal/months/${year}/${month}`);
}

export function getJournalDay(date: string, offset = 0): Promise<JournalDay> {
  return authedGet<JournalDay>(`/v1/portfolio/journal/days/${date}?offset=${offset}`);
}

export function getJournalWeek(start: string): Promise<JournalWeek> {
  return authedGet<JournalWeek>(`/v1/portfolio/journal/weeks/${start}`);
}
