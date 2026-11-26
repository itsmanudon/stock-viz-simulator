"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { createOrder, postTrade } from "@/lib/api/trading";
import { bookIdFromForm } from "@/lib/book-url";
import { REVIEW_REQUIRED_ERROR, clientOrderIdFrom, skippedReview } from "@/lib/order-review";
import { planFromForm } from "@/lib/plans";
import { titleCase } from "@/lib/title-case";

const TradeSchema = z.object({
  ticker: z
    .string()
    .min(1, "Ticker is required")
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  side: z.enum(["buy", "sell"]),
  quantity: z
    .string()
    .min(1, "Quantity is required")
    .refine((v) => Number(v) > 0, "Quantity must be positive"),
});

const OrderSchema = z.object({
  ticker: z
    .string()
    .min(1, "Ticker is required")
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  side: z.enum(["buy", "sell"]),
  order_type: z.enum(["limit", "stop_loss", "take_profit"]),
  quantity: z
    .string()
    .min(1, "Quantity is required")
    .refine((v) => Number(v) > 0, "Quantity must be positive"),
  limit_price: z
    .string()
    .min(1, "Limit price is required")
    .refine((v) => Number(v) > 0, "Limit price must be positive"),
});

export type TradeFormState = {
  error?: string;
  success?: {
    ticker: string;
    side: "buy" | "sell";
    quantity: string;
    price: string;
    currency: string;
    total_native: string;
    total_usd: string;
    /** A4.2: fees on the fill and the amount after them (null: none charged). */
    fees?: string | null;
    net_native?: string | null;
    /** A5.4: the fill was linked to a plan (which locked at it). */
    planned?: boolean;
  };
};

export type OrderFormState = {
  error?: string;
  success?: string;
};

export async function placeTradeAction(
  _prev: TradeFormState,
  formData: FormData,
): Promise<TradeFormState> {
  if (skippedReview(formData)) return { error: REVIEW_REQUIRED_ERROR };
  const parsed = TradeSchema.safeParse({
    ticker: formData.get("ticker"),
    side: formData.get("side"),
    quantity: formData.get("quantity"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  // A5.4: "Plan this trade" posts the plan with the order (buys only).
  const plan = parsed.data.side === "buy" ? planFromForm(formData) : null;
  if (plan && "error" in plan) return { error: plan.error };

  try {
    const trade = await postTrade(
      {
        ticker: parsed.data.ticker,
        side: parsed.data.side,
        quantity: parsed.data.quantity,
        client_order_id: clientOrderIdFrom(formData),
        plan,
      },
      bookIdFromForm(formData),
    );
    revalidatePath("/portfolio");
    revalidatePath("/trades");
    revalidatePath("/trade");
    revalidatePath("/orders");
    revalidatePath(`/stocks/${parsed.data.ticker}`);
    return {
      success: {
        ticker: trade.ticker,
        side: trade.side,
        quantity: trade.quantity,
        price: trade.price,
        currency: trade.currency,
        total_native: trade.total_native,
        total_usd: trade.total_usd,
        fees: trade.fees ?? null,
        net_native: trade.net_native ?? null,
        planned: Boolean(trade.trade_plan_id),
      },
    };
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return { error: "Sign in to place trades" };
    }
    if (err instanceof AuthedApiError) {
      // The API encodes its detail as ``{"detail": "..."}``; surface that.
      try {
        const parsedDetail = JSON.parse(err.detail) as { detail?: string };
        if (parsedDetail.detail) return { error: parsedDetail.detail };
      } catch {
        // fall through
      }
      return { error: err.detail || `API ${err.status}` };
    }
    throw err;
  }
}

export async function placeOrderAction(
  _prev: OrderFormState,
  formData: FormData,
): Promise<OrderFormState> {
  if (skippedReview(formData)) return { error: REVIEW_REQUIRED_ERROR };
  const parsed = OrderSchema.safeParse({
    ticker: formData.get("ticker"),
    side: formData.get("side"),
    order_type: formData.get("order_type"),
    quantity: formData.get("quantity"),
    limit_price: formData.get("limit_price"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  const plan = parsed.data.side === "buy" ? planFromForm(formData) : null;
  if (plan && "error" in plan) return { error: plan.error };

  try {
    const order = await createOrder(
      { ...parsed.data, client_order_id: clientOrderIdFrom(formData), plan },
      bookIdFromForm(formData),
    );
    revalidatePath("/orders");
    revalidatePath("/trade");
    revalidatePath(`/stocks/${parsed.data.ticker}`);
    const label = order.order_type.replace("_", " ");
    return {
      success: `${label.charAt(0).toUpperCase() + label.slice(1)} order placed: ${titleCase(order.side)} ${order.quantity} ${order.ticker} @ $${Number(order.limit_price).toFixed(2)}${order.trade_plan_id ? ". Its plan locks when it fills" : ""}`,
    };
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return { error: "Sign in to place orders" };
    }
    if (err instanceof AuthedApiError) {
      try {
        const parsedDetail = JSON.parse(err.detail) as { detail?: string };
        if (parsedDetail.detail) return { error: parsedDetail.detail };
      } catch {
        // fall through
      }
      return { error: err.detail || `API ${err.status}` };
    }
    throw err;
  }
}
