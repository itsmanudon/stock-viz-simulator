"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { apiDetailMessage } from "@/lib/api-error-message";
import { advanceDrill, cancelDrillOrder, submitDrillOrder } from "@/lib/api/drills";
import {
  advanceReplaySession,
  cancelReplayOrder,
  cancelReplaySession,
  createReplaySession,
  getReplayAvailability,
  putReplayJournal,
  submitReplayOrder,
} from "@/lib/api/replay";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { replayErrorMessage, toReplayTimestamp } from "@/lib/replay";

export type ReplayActionState = {
  error?: string;
  from?: string;
  to?: string;
  status?: string;
  filled?: boolean;
  fillPrice?: string;
  quantity?: string;
  side?: "buy" | "sell";
  /** A4.6: a resting order was placed (judged from the next bar). */
  placed?: boolean;
  orderType?: string;
  limitPrice?: string;
  /** A6.9: a bracket's stop and target. */
  stopPrice?: string;
  targetPrice?: string;
};

function mapError(err: unknown, drill = false): ReplayActionState {
  if (err instanceof UnauthenticatedError) {
    return { error: replayErrorMessage(401) };
  }
  if (err instanceof AuthedApiError) {
    // A4.7: a drill's errors are already masked by the API and say why
    // (the plan gate, cash, a finished drill).
    if (drill) return { error: apiDetailMessage(err.detail, replayErrorMessage(err.status)) };
    return { error: replayErrorMessage(err.status, err.detail) };
  }
  throw err;
}

/** A4.7: the ticket, steps and order list also serve a drill (`target=drill`,
 * `session_id` is then the drill's id). */
function isDrill(formData: FormData): boolean {
  return formData.get("target") === "drill";
}

function revalidateTarget(drill: boolean, id: number): void {
  if (drill) {
    revalidatePath("/drills");
    revalidatePath(`/drills/${id}`);
  } else {
    revalidatePath("/replay");
    revalidatePath(`/replay/${id}`);
  }
}

const CreateSchema = z.object({
  ticker: z
    .string()
    .min(1, "Choose a symbol")
    .max(16)
    .transform((value) => value.trim().toUpperCase()),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  starting_cash: z
    .string()
    .min(1, "Starting cash is required")
    .refine((value) => Number(value) > 0, "Starting cash must be greater than 0"),
  interval: z.enum(["1d", "1m", "5m", "15m", "60m"]).default("1d"),
  profile: z.enum(["legacy_close", "intrabar_ohlc"]).default("legacy_close"),
});

export async function createReplayAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const parsed = CreateSchema.safeParse({
    ticker: formData.get("ticker"),
    start: formData.get("start"),
    end: formData.get("end"),
    starting_cash: formData.get("starting_cash"),
    interval: formData.get("interval") ?? undefined,
    profile: formData.get("profile") ?? undefined,
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  const intraday = parsed.data.interval !== "1d";
  try {
    const session = await createReplaySession({
      ticker: parsed.data.ticker,
      start_at: toReplayTimestamp(parsed.data.start),
      // A6.9: an intraday session runs to its end date's last bar.
      end_at: intraday ? `${parsed.data.end}T23:59:59.000Z` : toReplayTimestamp(parsed.data.end),
      starting_cash: parsed.data.starting_cash,
      interval: parsed.data.interval,
      profile: parsed.data.profile,
    });
    revalidatePath("/replay");
    const params = new URLSearchParams({
      requestedStart: parsed.data.start,
      requestedEnd: parsed.data.end,
    });
    redirect(`/replay/${session.id}?${params.toString()}`);
  } catch (err) {
    return mapError(err);
  }
}

export async function loadReplayAvailabilityAction(ticker: string): Promise<{
  error?: string;
  first?: string;
  last?: string;
  bars?: number;
  currency?: string;
  lagDays?: number;
  maxEnd?: string | null;
  defaultCash?: string;
  feeSchedule?: string;
  tradable?: boolean;
  intervals?: string[];
  minuteFirst?: string | null;
  minuteLast?: string | null;
}> {
  try {
    const available = await getReplayAvailability(ticker);
    return {
      first: available.first_bar.slice(0, 10),
      last: available.last_bar.slice(0, 10),
      bars: available.bars_count,
      currency: available.currency,
      lagDays: available.lag_days,
      maxEnd: available.max_end,
      defaultCash: String(Math.round(Number(available.default_starting_cash))),
      feeSchedule: available.fee_schedule,
      tradable: available.tradable,
      intervals: available.intervals ?? ["1d"],
      minuteFirst: available.minute_first ? available.minute_first.slice(0, 10) : null,
      minuteLast: available.minute_last ? available.minute_last.slice(0, 10) : null,
    };
  } catch (err) {
    if (err instanceof AuthedApiError) {
      return { error: replayErrorMessage(err.status, err.detail) };
    }
    if (err instanceof UnauthenticatedError) {
      return { error: replayErrorMessage(401) };
    }
    throw err;
  }
}

export async function advanceReplayAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const sessionId = Number(formData.get("session_id"));
  const from = String(formData.get("current_at") ?? "");
  if (!Number.isInteger(sessionId) || sessionId <= 0) {
    return { error: "Invalid replay session." };
  }
  const drill = isDrill(formData);
  try {
    const session = drill
      ? await advanceDrill(sessionId, from || undefined)
      : await advanceReplaySession(sessionId, from || undefined);
    revalidateTarget(drill, sessionId);
    return { from, to: session.current_at, status: session.status };
  } catch (err) {
    return mapError(err, drill);
  }
}

/** A6.9: one autoplay step's outcome. */
export type AutoplayStep = {
  /** The bar the session is on after the step (unchanged when it was refused). */
  to?: string;
  status?: string;
  hasNext?: boolean;
  /** The API's per-user advance limit refused the step: try again after this. */
  retryAfterMs?: number;
  error?: string;
};

/**
 * A6.9: one autoplay step from the bar on screen (`currentAt`). The API's
 * `expected_current_at` guard makes a repeated or late step change nothing,
 * so autoplay never moves two bars for one step. No revalidation here: the
 * player refreshes the page itself, so steps are not held up by rendering.
 */
export async function autoplayStepAction(
  sessionId: number,
  currentAt: string,
): Promise<AutoplayStep> {
  if (!Number.isInteger(sessionId) || sessionId <= 0 || !currentAt) {
    return { error: "Invalid replay session." };
  }
  try {
    const session = await advanceReplaySession(sessionId, currentAt);
    return { to: session.current_at, status: session.status, hasNext: session.has_next };
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 429) {
      return { to: currentAt, retryAfterMs: 1000 };
    }
    const mapped = mapError(err);
    return { error: mapped.error };
  }
}

export async function cancelReplayAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const sessionId = Number(formData.get("session_id"));
  if (!Number.isInteger(sessionId) || sessionId <= 0) {
    return { error: "Invalid replay session." };
  }
  try {
    const session = await cancelReplaySession(sessionId);
    revalidatePath("/replay");
    revalidatePath(`/replay/${sessionId}`);
    return { status: session.status };
  } catch (err) {
    return mapError(err);
  }
}

const OrderSchema = z
  .object({
    session_id: z.string().regex(/^\d+$/),
    side: z.enum(["buy", "sell"]),
    order_type: z
      .enum(["market", "limit", "stop_loss", "take_profit", "bracket"])
      .default("market"),
    quantity: z
      .string()
      .min(1, "Quantity is required")
      .refine((value) => Number(value) > 0, "Quantity must be positive"),
    limit_price: z.string().optional(),
    entry_type: z.enum(["market", "limit"]).default("market"),
    stop_price: z.string().optional(),
    target_price: z.string().optional(),
  })
  .refine(
    (value) =>
      value.order_type === "market" ||
      (value.order_type === "bracket" && value.entry_type === "market") ||
      (value.limit_price !== undefined && Number(value.limit_price) > 0),
    { message: "Enter a positive price for a limit or stop order", path: ["limit_price"] },
  )
  .refine(
    (value) =>
      value.order_type !== "bracket" ||
      (Number(value.stop_price) > 0 && Number(value.target_price) > 0),
    { message: "A bracket needs a positive stop and target", path: ["stop_price"] },
  )
  .refine(
    (value) =>
      !(value.order_type === "stop_loss" || value.order_type === "take_profit") ||
      value.side === "sell",
    { message: "Stop-loss and take-profit orders are sell-only", path: ["side"] },
  );

export async function submitReplayOrderAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const parsed = OrderSchema.safeParse({
    session_id: formData.get("session_id"),
    side: formData.get("side"),
    order_type: formData.get("order_type") ?? undefined,
    quantity: formData.get("quantity"),
    limit_price: formData.get("limit_price") || undefined,
    entry_type: formData.get("entry_type") ?? undefined,
    stop_price: formData.get("stop_price") || undefined,
    target_price: formData.get("target_price") || undefined,
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  const sessionId = Number(parsed.data.session_id);
  const drill = isDrill(formData);
  try {
    const order = {
      side: parsed.data.side,
      order_type: parsed.data.order_type,
      quantity: parsed.data.quantity,
      limit_price: parsed.data.limit_price,
      entry_type: parsed.data.entry_type,
      stop_price: parsed.data.stop_price,
      target_price: parsed.data.target_price,
    };
    const result = drill
      ? await submitDrillOrder(sessionId, order)
      : await submitReplayOrder(sessionId, order);
    revalidateTarget(drill, sessionId);
    if (result.order?.order_type === "bracket") {
      const legs = result.children ?? [];
      return {
        placed: true,
        side: "buy",
        quantity: result.order.quantity,
        orderType: "bracket",
        limitPrice: result.order.limit_price,
        stopPrice: legs.find((l) => l.order_type === "stop_loss")?.limit_price,
        targetPrice: legs.find((l) => l.order_type === "take_profit")?.limit_price,
      };
    }
    if (result.order) {
      return {
        placed: true,
        side: parsed.data.side,
        quantity: result.order.quantity,
        orderType: result.order.order_type,
        limitPrice: result.order.limit_price,
      };
    }
    if (result.decision?.status === "filled" && result.fill) {
      return {
        filled: true,
        fillPrice: result.fill.fill_price,
        quantity: result.fill.quantity,
        side: parsed.data.side,
      };
    }
    return { error: "The order did not fill at this session's close." };
  } catch (err) {
    return mapError(err, drill);
  }
}

export async function cancelReplayOrderAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const sessionId = Number(formData.get("session_id"));
  const orderId = Number(formData.get("order_id"));
  if (!Number.isInteger(sessionId) || sessionId <= 0 || !Number.isInteger(orderId)) {
    return { error: "Invalid replay order." };
  }
  const drill = isDrill(formData);
  try {
    const order = drill
      ? await cancelDrillOrder(sessionId, orderId)
      : await cancelReplayOrder(sessionId, orderId);
    revalidateTarget(drill, sessionId);
    return { status: order.status };
  } catch (err) {
    return mapError(err, drill);
  }
}

const JournalSchema = z.object({
  session_id: z.string().regex(/^\d+$/),
  thesis: z.string().max(4000).optional(),
  invalidation: z.string().max(4000).optional(),
  expected_holding_bars: z.string().optional(),
  confidence: z.string().optional(),
  reflection: z.string().max(8000).optional(),
});

function emptyToNull(value: string | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed.length === 0 ? null : trimmed;
}

export async function saveReplayJournalAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const parsed = JournalSchema.safeParse({
    session_id: formData.get("session_id"),
    thesis: formData.get("thesis") ?? undefined,
    invalidation: formData.get("invalidation") ?? undefined,
    expected_holding_bars: formData.get("expected_holding_bars") ?? undefined,
    confidence: formData.get("confidence") ?? undefined,
    reflection: formData.get("reflection") ?? undefined,
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid journal." };
  }
  const sessionId = Number(parsed.data.session_id);
  const barsRaw = parsed.data.expected_holding_bars?.trim() ?? "";
  const confidenceRaw = parsed.data.confidence?.trim() ?? "";
  try {
    await putReplayJournal(sessionId, {
      thesis: emptyToNull(parsed.data.thesis),
      invalidation: emptyToNull(parsed.data.invalidation),
      expected_holding_bars: barsRaw === "" ? null : Number(barsRaw),
      confidence: confidenceRaw === "" ? null : Number(confidenceRaw),
      reflection: emptyToNull(parsed.data.reflection),
    });
    revalidatePath(`/replay/${sessionId}`);
    return { status: "saved" };
  } catch (err) {
    return mapError(err);
  }
}
