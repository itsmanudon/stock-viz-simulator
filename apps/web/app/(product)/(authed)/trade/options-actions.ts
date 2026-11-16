"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { closeStrategy, openStrategy, tradeOption } from "@/lib/api/options";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { clientOrderIdFrom } from "@/lib/order-review";

const OpenSchema = z.object({
  ticker: z
    .string()
    .min(1, "Symbol is required")
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  option_type: z.enum(["call", "put"]),
  side: z.enum(["long", "short"]).default("long"),
  strike: z
    .string()
    .min(1, "Strike is required")
    .refine((v) => Number(v) > 0, "Strike must be positive"),
  expiry: z.string().min(1, "Expiry is required"),
  quantity: z
    .string()
    .min(1, "Contracts is required")
    .refine(
      (v) => Number.isInteger(Number(v)) && Number(v) > 0,
      "Contracts must be a whole number",
    ),
});

export type OptionTradeState = {
  error?: string;
  success?: {
    ticker: string;
    option_type: "call" | "put";
    strike: string;
    quantity: number;
    premium_paid: string;
    side: "long" | "short";
  };
};

function apiErrorMessage(err: AuthedApiError): string {
  try {
    const parsed = JSON.parse(err.detail) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // fall through
  }
  return err.detail || `API ${err.status}`;
}

export async function openOptionAction(
  _prev: OptionTradeState,
  formData: FormData,
): Promise<OptionTradeState> {
  const parsed = OpenSchema.safeParse({
    ticker: formData.get("ticker"),
    option_type: formData.get("option_type"),
    side: formData.get("side") ?? undefined,
    strike: formData.get("strike"),
    expiry: formData.get("expiry"),
    quantity: formData.get("quantity"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  try {
    const result = await tradeOption({
      action: "open",
      ticker: parsed.data.ticker,
      option_type: parsed.data.option_type,
      side: parsed.data.side,
      strike: parsed.data.strike,
      expiry: parsed.data.expiry,
      quantity: Number(parsed.data.quantity),
      client_order_id: clientOrderIdFrom(formData),
    });
    revalidatePath("/portfolio");
    revalidatePath("/trade");
    return {
      success: {
        ticker: result.position.ticker,
        option_type: result.position.option_type,
        strike: result.position.strike,
        quantity: result.position.quantity,
        premium_paid: result.position.premium_paid,
        side: result.position.side ?? "long",
      },
    };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to trade options" };
    if (err instanceof AuthedApiError) return { error: apiErrorMessage(err) };
    throw err;
  }
}

export async function closeOptionAction(formData: FormData): Promise<void> {
  const idRaw = formData.get("option_id");
  const optionId = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(optionId)) return;
  try {
    await tradeOption({ action: "close", option_id: optionId });
  } catch (err) {
    if (err instanceof UnauthenticatedError) return;
    if (err instanceof AuthedApiError && err.status === 404) {
      // already gone — no-op
    } else {
      throw err;
    }
  }
  revalidatePath("/portfolio");
  revalidatePath("/trade");
}

export type CloseOptionState = { error: string | null; closed: boolean };

/**
 * Close from the portfolio table (audit LG-8). A refused close, such as an
 * expired contract awaiting settlement (400), comes back as a message for the
 * form instead of throwing to the app error page.
 */
export async function closeOptionFormAction(
  _prev: CloseOptionState,
  formData: FormData,
): Promise<CloseOptionState> {
  const idRaw = formData.get("option_id");
  const optionId = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(optionId)) return { error: "Unknown option position", closed: false };
  try {
    await tradeOption({ action: "close", option_id: optionId });
  } catch (err) {
    if (err instanceof UnauthenticatedError)
      return { error: "Sign in to close options", closed: false };
    if (err instanceof AuthedApiError) {
      if (err.status !== 404) return { error: apiErrorMessage(err), closed: false };
      // Already gone: treat as closed.
    } else {
      throw err;
    }
  }
  revalidatePath("/portfolio");
  revalidatePath("/trade");
  return { error: null, closed: true };
}

// ---------------------------------------------------------------------------
// Strategies (Phase 9.5)
// ---------------------------------------------------------------------------

const StrategySchema = z.object({
  kind: z.enum([
    "covered_call",
    "cash_secured_put",
    "protective_put",
    "bull_call",
    "bear_put",
    "bull_put",
    "bear_call",
    "iron_condor",
    "straddle",
    "strangle",
    "calendar",
  ]),
  ticker: z
    .string()
    .min(1)
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  strikes: z
    .array(z.string().refine((v) => Number(v) > 0, "Strikes must be positive"))
    .min(1)
    .max(4),
  expiry: z.string().min(1, "Expiry is required"),
  far_expiry: z.string().optional(),
  option_type: z.enum(["call", "put"]).optional(),
  quantity: z
    .string()
    .refine(
      (v) => Number.isInteger(Number(v)) && Number(v) > 0,
      "Contracts must be a whole number",
    ),
});

export type StrategyTradeState = {
  error?: string;
  success?: { id: number; label: string; ticker: string; cash_delta: string };
};

/**
 * Open a strategy from the builder. Two-step like the stock tickets (UX-4):
 * a post without `review_step=confirmed` is refused, so a form submitted
 * before the review cannot open anything.
 */
export async function openStrategyAction(
  _prev: StrategyTradeState,
  formData: FormData,
): Promise<StrategyTradeState> {
  if (formData.get("review_step") !== "confirmed") {
    return { error: "Review the strategy before placing it" };
  }
  const parsed = StrategySchema.safeParse({
    kind: formData.get("kind"),
    ticker: formData.get("ticker"),
    strikes: formData.getAll("strike").map(String),
    expiry: formData.get("expiry"),
    far_expiry: formData.get("far_expiry") || undefined,
    option_type: formData.get("option_type") || undefined,
    quantity: formData.get("quantity"),
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  try {
    const result = await openStrategy({
      ...parsed.data,
      quantity: Number(parsed.data.quantity),
      client_order_id: clientOrderIdFrom(formData),
    });
    revalidatePath("/portfolio");
    revalidatePath("/trade");
    return {
      success: {
        id: result.strategy.id,
        label: result.strategy.label,
        ticker: parsed.data.ticker,
        cash_delta: result.cash_delta,
      },
    };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to trade options" };
    if (err instanceof AuthedApiError) return { error: apiErrorMessage(err) };
    throw err;
  }
}

/** Close a whole strategy from the portfolio (every open leg, one net payment). */
export async function closeStrategyFormAction(
  _prev: CloseOptionState,
  formData: FormData,
): Promise<CloseOptionState> {
  const idRaw = formData.get("strategy_id");
  const id = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(id)) return { error: "Unknown strategy", closed: false };
  try {
    await closeStrategy(id);
  } catch (err) {
    if (err instanceof UnauthenticatedError)
      return { error: "Sign in to close strategies", closed: false };
    if (err instanceof AuthedApiError) return { error: apiErrorMessage(err), closed: false };
    throw err;
  }
  revalidatePath("/portfolio");
  revalidatePath("/trade");
  return { error: null, closed: true };
}
