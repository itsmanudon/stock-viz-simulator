"use server";

import { revalidatePath } from "next/cache";

import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { cancelOrder } from "@/lib/api/trading";

export async function cancelOrderAction(formData: FormData): Promise<void> {
  const idRaw = formData.get("id");
  const id = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(id)) return;
  try {
    await cancelOrder(id);
  } catch (err) {
    if (err instanceof AuthedApiError && (err.status === 404 || err.status === 400)) {
      // already cancelled or not found — no-op
    } else if (err instanceof UnauthenticatedError) {
      return;
    } else {
      throw err;
    }
  }
  revalidatePath("/orders");
}
