"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { createOrder, postTrade } from "@/lib/api/trading";

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
  const parsed = TradeSchema.safeParse({
    ticker: formData.get("ticker"),
    side: formData.get("side"),
    quantity: formData.get("quantity"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  try {
    const trade = await postTrade({
      ticker: parsed.data.ticker,
      side: parsed.data.side,
      quantity: parsed.data.quantity,
    });
    revalidatePath("/portfolio");
    revalidatePath("/trades");
    revalidatePath("/trade");
    return {
      success: {
        ticker: trade.ticker,
        side: trade.side,
        quantity: trade.quantity,
        price: trade.price,
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

  try {
    const order = await createOrder(parsed.data);
    revalidatePath("/orders");
    const label = order.order_type.replace("_", " ");
    return {
      success: `${label.charAt(0).toUpperCase() + label.slice(1)} order placed: ${order.side.toUpperCase()} ${order.quantity} ${order.ticker} @ $${Number(order.limit_price).toFixed(2)}`,
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
