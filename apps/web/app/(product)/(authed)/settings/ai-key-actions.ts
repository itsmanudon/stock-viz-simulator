"use server";

import { revalidatePath } from "next/cache";

import { apiDetail } from "@/lib/api-error-detail";
import { deleteAiKey, saveAiKey } from "@/lib/api/ai-server";
import { AuthedApiError } from "@/lib/api/server";

export type AiKeyState = { ok?: string; error?: string };

export async function saveAiKeyAction(_prev: AiKeyState, form: FormData): Promise<AiKeyState> {
  const provider = String(form.get("provider") ?? "openai_compatible");
  const apiKey = String(form.get("api_key") ?? "").trim();
  const model = String(form.get("model") ?? "").trim();
  const baseUrl = String(form.get("base_url") ?? "").trim();
  if (apiKey.length < 8) return { error: "Paste the whole key." };
  if (!model) return { error: "Name the model to use." };
  try {
    await saveAiKey(provider, { api_key: apiKey, model, base_url: baseUrl || null });
  } catch (err) {
    if (err instanceof AuthedApiError)
      return { error: apiDetail(err.detail, "The key was not saved.") };
    return { error: "The key was not saved." };
  }
  revalidatePath("/settings");
  return { ok: "Saved. The key is encrypted and will not be shown again." };
}

export async function deleteAiKeyAction(provider: string): Promise<AiKeyState> {
  try {
    await deleteAiKey(provider);
  } catch (err) {
    if (err instanceof AuthedApiError)
      return { error: apiDetail(err.detail, "The key was not removed.") };
    return { error: "The key was not removed." };
  }
  revalidatePath("/settings");
  return { ok: "Removed." };
}
