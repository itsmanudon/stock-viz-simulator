"use server";

import { revalidatePath } from "next/cache";

import { deleteScreen, saveScreen } from "@/lib/api/screens";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

export type ScreenActionState = { saved?: string; error?: string };

/** Save the screen on show under a name (Phase 6.2). Same name replaces it. */
export async function saveScreenAction(
  _prev: ScreenActionState,
  formData: FormData,
): Promise<ScreenActionState> {
  const name = String(formData.get("name") ?? "").trim();
  const query = String(formData.get("query") ?? "");
  if (!name) return { error: "Give the screen a name." };
  try {
    await saveScreen(name.slice(0, 80), query);
    revalidatePath("/screener");
    return { saved: name };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to save screens." };
    if (err instanceof AuthedApiError && err.status === 409) return { error: err.message };
    return { error: "The screen could not be saved." };
  }
}

export async function deleteScreenAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("id"));
  if (!Number.isInteger(id) || id <= 0) return;
  try {
    await deleteScreen(id);
  } catch (err) {
    if (!(err instanceof UnauthenticatedError)) throw err;
  }
  revalidatePath("/screener");
}
