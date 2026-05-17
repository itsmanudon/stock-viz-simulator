"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { deleteCommentApi, postComment } from "@/lib/api/comments";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

const CreateSchema = z.object({
  ticker: z
    .string()
    .min(1)
    .max(16)
    .transform((s) => s.trim().toUpperCase()),
  body: z.string().trim().min(1, "Comment cannot be empty").max(2000, "Comment is too long"),
  parent_id: z.string().optional(),
});

export type PostCommentState = {
  error?: string;
  postedAt?: string;
};

function apiErrorDetail(err: AuthedApiError): string {
  try {
    const parsed = JSON.parse(err.detail) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // fall through to raw text
  }
  return err.detail || `API ${err.status}`;
}

export async function postCommentAction(
  _prev: PostCommentState,
  formData: FormData,
): Promise<PostCommentState> {
  const parsed = CreateSchema.safeParse({
    ticker: formData.get("ticker"),
    body: formData.get("body"),
    parent_id: formData.get("parent_id") || undefined,
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  const parentId = parsed.data.parent_id ? Number(parsed.data.parent_id) : undefined;

  try {
    await postComment(parsed.data.ticker, {
      body: parsed.data.body,
      parent_id: Number.isFinite(parentId) ? parentId : undefined,
    });
    revalidatePath(`/stocks/${parsed.data.ticker}`);
    return { postedAt: new Date().toISOString() };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to post a comment" };
    if (err instanceof AuthedApiError) return { error: apiErrorDetail(err) };
    throw err;
  }
}

export async function deleteCommentAction(formData: FormData): Promise<void> {
  const idRaw = formData.get("id");
  const ticker = formData.get("ticker");
  const id = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(id)) return;
  try {
    await deleteCommentApi(id);
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 404) {
      // already gone — no-op
    } else if (err instanceof UnauthenticatedError) {
      return;
    } else {
      throw err;
    }
  }
  if (typeof ticker === "string") {
    revalidatePath(`/stocks/${ticker.toUpperCase()}`);
  }
}
