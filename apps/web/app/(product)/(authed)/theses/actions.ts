"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { closeThesis, createThesis, updateThesis } from "@/lib/api/theses-server";

export type ThesisFormState = { error?: string; saved?: boolean };

const ThesisSchema = z.object({
  ticker: z.string().trim().min(1, "Ticker is required").max(16),
  title: z.string().trim().min(1, "Title is required").max(160),
  body: z.string().trim().min(1, "Write the thesis").max(20000),
  kill_rule: z.string().trim().max(2000).optional(),
});

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof AuthedApiError) {
    const text = err.detail;
    try {
      const body = JSON.parse(text) as { detail?: unknown };
      if (typeof body.detail === "string") return body.detail;
      const detail = body.detail as { message?: string } | undefined;
      if (detail?.message) return `Kill rule: ${detail.message}`;
    } catch {
      return text || fallback;
    }
  }
  return fallback;
}

/** A7.5: write a thesis; a kill rule arms its kill switch. */
export async function createThesisAction(
  _prev: ThesisFormState,
  formData: FormData,
): Promise<ThesisFormState> {
  const parsed = ThesisSchema.safeParse({
    ticker: formData.get("ticker"),
    title: formData.get("title"),
    body: formData.get("body"),
    kill_rule: formData.get("kill_rule") || undefined,
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  try {
    await createThesis({ ...parsed.data, kill_rule: parsed.data.kill_rule || null });
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to write a thesis." };
    return { error: apiMessage(err, "The thesis could not be saved.") };
  }
  revalidatePath("/theses");
  return { saved: true };
}

function thesisId(formData: FormData): number | null {
  const id = Number(formData.get("id"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** Close a thesis (played out) or mark it invalidated; its kill switch pauses. */
export async function closeThesisAction(formData: FormData): Promise<void> {
  const id = thesisId(formData);
  const status = formData.get("status") === "invalidated" ? "invalidated" : "closed";
  if (id === null) return;
  try {
    await closeThesis(id, status);
  } catch (err) {
    if (!(err instanceof UnauthenticatedError) && !(err instanceof AuthedApiError)) throw err;
  }
  revalidatePath("/theses");
}

/** Remove a thesis's kill rule (its alert is deleted). */
export async function removeKillRuleAction(formData: FormData): Promise<void> {
  const id = thesisId(formData);
  if (id === null) return;
  try {
    await updateThesis(id, { kill_rule: null });
  } catch (err) {
    if (!(err instanceof UnauthenticatedError) && !(err instanceof AuthedApiError)) throw err;
  }
  revalidatePath("/theses");
}
