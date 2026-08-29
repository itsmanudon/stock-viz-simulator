"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { tradeOption } from "@/lib/api/options";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

const OpenSchema = z.object({
  ticker: z
    .string()
    .min(1, "Symbol is required")
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  option_type: z.enum(["call", "put"]),
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
      strike: parsed.data.strike,
      expiry: parsed.data.expiry,
      quantity: Number(parsed.data.quantity),
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
