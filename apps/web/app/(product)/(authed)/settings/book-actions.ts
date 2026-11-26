"use server";

/**
 * Settings → Books (A5.2): create, rename, make default, archive or
 * unarchive, and delete, through `/v1/books` (A5.1). The API holds the rules
 * (20 books, unique names, one paper default, delete only when empty or
 * archived) and answers 409/422 with the reason, which the form shows.
 */

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { createBook, deleteBook, updateBook } from "@/lib/api/books";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { importedBookCurrency } from "@/lib/tradebook-import";

export type BookActionState = { error?: string; ok?: string };

const CreateSchema = z.object({
  name: z.string().trim().min(1, "Name the book").max(60, "60 characters at most"),
  kind: z.enum(["paper", "imported"]).default("paper"),
  base_currency: z.enum(["USD", "INR"]),
  broker: z
    .enum(["zerodha", "dhan", "fyers", "upstox", "angelone", "groww", "other"])
    .default("zerodha"),
  holder_kind: z.enum(["self", "family", "huf"]),
  holder_label: z
    .string()
    .trim()
    .max(60, "60 characters at most")
    .transform((v) => (v === "" ? null : v)),
});

function refresh() {
  for (const path of ["/settings", "/portfolio", "/dashboard", "/trade", "/orders", "/trades"]) {
    revalidatePath(path);
  }
  // The switcher lives in the product layout.
  revalidatePath("/", "layout");
}

function apiMessage(err: unknown): BookActionState {
  if (err instanceof UnauthenticatedError) return { error: "Sign in to manage books" };
  if (err instanceof AuthedApiError) {
    try {
      const parsed = JSON.parse(err.detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") return { error: parsed.detail };
      if (Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] as { msg?: string } | undefined;
        if (first?.msg) return { error: first.msg.replace(/^Value error, /, "") };
      }
    } catch {
      // fall through
    }
    return { error: err.detail || `API ${err.status}` };
  }
  throw err;
}

function bookId(formData: FormData): number | null {
  const raw = Number(formData.get("book_id"));
  return Number.isSafeInteger(raw) && raw > 0 ? raw : null;
}

export async function createBookAction(
  _prev: BookActionState,
  formData: FormData,
): Promise<BookActionState> {
  const parsed = CreateSchema.safeParse({
    name: formData.get("name") ?? "",
    kind: formData.get("kind") ?? "paper",
    base_currency: formData.get("base_currency"),
    broker: formData.get("broker") || "zerodha",
    holder_kind: formData.get("holder_kind") ?? "self",
    holder_label: formData.get("holder_label") ?? "",
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  // A5.3, A6.11: an Indian broker's tradebook is in rupees; "other" (your own
  // column map) takes the chosen currency, USD for a US broker. A paper book
  // has no broker.
  const { broker, ...rest } = parsed.data;
  const body =
    rest.kind === "imported"
      ? { ...rest, broker, base_currency: importedBookCurrency(broker, rest.base_currency) }
      : rest;
  try {
    const book = await createBook(body);
    refresh();
    return { ok: `Created ${book.name} (${book.base_currency}).` };
  } catch (err) {
    return apiMessage(err);
  }
}

export async function renameBookAction(
  _prev: BookActionState,
  formData: FormData,
): Promise<BookActionState> {
  const id = bookId(formData);
  const name = String(formData.get("name") ?? "").trim();
  if (!id) return { error: "Unknown book" };
  if (!name) return { error: "Name the book" };
  const holderKind = formData.get("holder_kind");
  const label = String(formData.get("holder_label") ?? "").trim();
  try {
    await updateBook(id, {
      name,
      ...(holderKind === "self" || holderKind === "family" || holderKind === "huf"
        ? { holder_kind: holderKind, holder_label: label === "" ? null : label }
        : {}),
    });
    refresh();
    return { ok: `Saved ${name}.` };
  } catch (err) {
    return apiMessage(err);
  }
}

/** `op`: `default`, `archive` or `unarchive`. */
export async function bookStateAction(
  _prev: BookActionState,
  formData: FormData,
): Promise<BookActionState> {
  const id = bookId(formData);
  const op = formData.get("op");
  if (!id) return { error: "Unknown book" };
  try {
    if (op === "default") await updateBook(id, { is_default: true });
    else if (op === "archive") await updateBook(id, { archived: true });
    else if (op === "unarchive") await updateBook(id, { archived: false });
    else return { error: "Unknown action" };
    refresh();
    return {
      ok:
        op === "default" ? "Default book changed." : op === "archive" ? "Archived." : "Unarchived.",
    };
  } catch (err) {
    return apiMessage(err);
  }
}

/** Two-step on the page: the form only posts after the name is typed back. */
export async function deleteBookAction(
  _prev: BookActionState,
  formData: FormData,
): Promise<BookActionState> {
  const id = bookId(formData);
  if (!id) return { error: "Unknown book" };
  if (formData.get("confirm_name") !== formData.get("expected_name")) {
    return { error: "Type the book's name to delete it" };
  }
  try {
    await deleteBook(id);
    refresh();
    return { ok: "Deleted." };
  } catch (err) {
    return apiMessage(err);
  }
}
