"use server";

/**
 * Journal entry review (A5.5): the user's text through
 * `PATCH /v1/journal/entries/{id}`. Figures are never sent: the API computes
 * them on read.
 */

import { revalidatePath } from "next/cache";

import { patchJournalEntry } from "@/lib/api/journal-entries";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { splitEntryTags } from "@/lib/journal-entries";

export type EntryReviewState = { error?: string; ok?: string };

function text(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

export async function saveEntryReviewAction(
  _prev: EntryReviewState,
  formData: FormData,
): Promise<EntryReviewState> {
  const id = Number(formData.get("entry_id"));
  if (!Number.isInteger(id) || id <= 0) return { error: "Unknown journal entry" };
  try {
    await patchJournalEntry(id, {
      review_notes: text(formData, "review_notes"),
      mistakes: text(formData, "mistakes"),
      lessons: text(formData, "lessons"),
      setup_tags: splitEntryTags(text(formData, "setup_tags")),
      mistake_tags: splitEntryTags(text(formData, "mistake_tags")),
    });
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to save your review" };
    if (err instanceof AuthedApiError) {
      try {
        const parsed = JSON.parse(err.detail) as { detail?: unknown };
        if (typeof parsed.detail === "string") return { error: parsed.detail };
        if (Array.isArray(parsed.detail)) {
          const first = parsed.detail[0] as { msg?: string } | undefined;
          if (first?.msg) return { error: first.msg };
        }
      } catch {
        // fall through
      }
      return { error: err.detail || `API ${err.status}` };
    }
    throw err;
  }
  revalidatePath(`/portfolio/journal/${id}`);
  revalidatePath("/portfolio");
  return { ok: "Review saved" };
}
