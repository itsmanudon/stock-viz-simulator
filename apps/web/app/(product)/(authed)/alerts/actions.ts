"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { createAlert, deleteAlert, dismissAlert } from "@/lib/api/alerts";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

const CreateSchema = z.object({
  ticker: z
    .string()
    .min(1, "Ticker is required")
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  direction: z.enum(["above", "below"]),
  target_price: z
    .string()
    .min(1, "Target price is required")
    .refine((v) => Number(v) > 0, "Target price must be positive"),
});

export type CreateAlertState = {
  error?: string;
  createdId?: number;
};

function apiErrorDetail(err: AuthedApiError): string {
  try {
    const parsed = JSON.parse(err.detail) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // fall through
  }
  return err.detail || `API ${err.status}`;
}

export async function createAlertAction(
  _prev: CreateAlertState,
  formData: FormData,
): Promise<CreateAlertState> {
  const parsed = CreateSchema.safeParse({
    ticker: formData.get("ticker"),
    direction: formData.get("direction"),
    target_price: formData.get("target_price"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  try {
    const alert = await createAlert({
      ticker: parsed.data.ticker,
      direction: parsed.data.direction,
      target_price: parsed.data.target_price,
    });
    revalidatePath(`/stocks/${alert.ticker}`);
    revalidatePath("/alerts");
    revalidatePath("/watchlist");
    return { createdId: alert.id };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to set alerts" };
    if (err instanceof AuthedApiError) return { error: apiErrorDetail(err) };
    throw err;
  }
}

export async function deleteAlertAction(formData: FormData): Promise<void> {
  const idRaw = formData.get("id");
  const id = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(id)) return;
  try {
    await deleteAlert(id);
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 404) {
      // already gone; no-op
    } else if (err instanceof UnauthenticatedError) {
      return;
    } else {
      throw err;
    }
  }
  revalidatePath("/");
  revalidatePath("/alerts");
}

export async function dismissAlertAction(formData: FormData): Promise<void> {
  const idRaw = formData.get("id");
  const id = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(id)) return;
  try {
    await dismissAlert(id);
  } catch (err) {
    if (err instanceof AuthedApiError && (err.status === 404 || err.status === 422)) {
      // ignore
    } else if (err instanceof UnauthenticatedError) {
      return;
    } else {
      throw err;
    }
  }
  revalidatePath("/");
  revalidatePath("/alerts");
}
