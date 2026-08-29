"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import {
  advanceReplaySession,
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
};

function mapError(err: unknown): ReplayActionState {
  if (err instanceof UnauthenticatedError) {
    return { error: replayErrorMessage(401) };
  }
  if (err instanceof AuthedApiError) {
    return { error: replayErrorMessage(err.status, err.detail) };
  }
  throw err;
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
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  try {
    const session = await createReplaySession({
      ticker: parsed.data.ticker,
      start_at: toReplayTimestamp(parsed.data.start),
      end_at: toReplayTimestamp(parsed.data.end),
      starting_cash: parsed.data.starting_cash,
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
}> {
  try {
    const available = await getReplayAvailability(ticker);
    return {
      first: available.first_bar.slice(0, 10),
      last: available.last_bar.slice(0, 10),
      bars: available.bars_count,
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
  try {
    const session = await advanceReplaySession(sessionId);
    revalidatePath("/replay");
    revalidatePath(`/replay/${sessionId}`);
    return { from, to: session.current_at, status: session.status };
  } catch (err) {
    return mapError(err);
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

const OrderSchema = z.object({
  session_id: z.string().regex(/^\d+$/),
  side: z.enum(["buy", "sell"]),
  quantity: z
    .string()
    .min(1, "Quantity is required")
    .refine((value) => Number(value) > 0, "Quantity must be positive"),
});

export async function submitReplayOrderAction(
  _prev: ReplayActionState,
  formData: FormData,
): Promise<ReplayActionState> {
  const parsed = OrderSchema.safeParse({
    session_id: formData.get("session_id"),
    side: formData.get("side"),
    quantity: formData.get("quantity"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  const sessionId = Number(parsed.data.session_id);
  try {
    const result = await submitReplayOrder(sessionId, {
      side: parsed.data.side,
      order_type: "market",
      quantity: parsed.data.quantity,
    });
    revalidatePath("/replay");
    revalidatePath(`/replay/${sessionId}`);
    if (result.decision.status === "filled" && result.fill) {
      return {
        filled: true,
        fillPrice: result.fill.fill_price,
        quantity: result.fill.quantity,
        side: parsed.data.side,
      };
    }
    return { error: "The order did not fill at this session's close." };
  } catch (err) {
    return mapError(err);
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
