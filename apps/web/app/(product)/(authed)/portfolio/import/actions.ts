"use server";

/**
 * A5.3: the tradebook import's server actions. The browser posts the file to
 * these actions (never to the API); each reads it, checks its size and type,
 * and sends the bytes to the API as `text/csv`. Nothing here logs the file or
 * any value from it. `next.config.ts` raises the server-action body limit
 * (Next 16 default 1 MB) to the importer's 2 MB cap plus form overhead.
 */

import { revalidatePath } from "next/cache";
import { z } from "zod";

import {
  type ImportCommit,
  type ImportPreview,
  addOpeningLot,
  commitImport,
  deleteImport,
  deleteImportMap,
  deleteOpeningLot,
  previewImport,
  saveImportMap,
} from "@/lib/api/imports";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { bookIdFromForm } from "@/lib/book-url";
import { MAP_FIELDS, checkTradebookFile, mappingProblem } from "@/lib/tradebook-import";

export type PreviewState = { error?: string; preview?: ImportPreview };
export type CommitState = { error?: string; result?: ImportCommit };
export type ImportActionState = { error?: string; ok?: string };
export type SaveMapState = { error?: string; id?: number; name?: string };

/** The column map a form names: "auto", a built-in map, or `saved:<id>`. */
function mapChoice(formData: FormData): string {
  const raw = String(formData.get("map") ?? "auto");
  return /^(auto|[a-z0-9_]{1,40}|saved:\d{1,9})$/.test(raw) ? raw : "auto";
}

function message(err: unknown): string {
  if (err instanceof UnauthenticatedError) return "Sign in to import trades";
  if (err instanceof AuthedApiError) {
    try {
      const parsed = JSON.parse(err.detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
      if (Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] as { msg?: string } | undefined;
        if (first?.msg) return first.msg.replace(/^Value error, /, "");
      }
    } catch {
      // fall through
    }
    return err.status === 413
      ? "The file is larger than 2 MB"
      : `The import failed (${err.status})`;
  }
  throw err;
}

function refresh() {
  for (const path of ["/portfolio", "/portfolio/import", "/dashboard", "/trades"]) {
    revalidatePath(path);
  }
}

async function fileBytes(formData: FormData): Promise<{ bytes?: ArrayBuffer; error?: string }> {
  const file = formData.get("file");
  if (!(file instanceof File)) return { error: "Choose a tradebook CSV file" };
  const problem = checkTradebookFile({ name: file.name, size: file.size, type: file.type });
  if (problem) return { error: problem };
  return { bytes: await file.arrayBuffer() };
}

export async function previewTradebookAction(formData: FormData): Promise<PreviewState> {
  const book = bookIdFromForm(formData);
  if (book == null) return { error: "Choose an imported book" };
  const { bytes, error } = await fileBytes(formData);
  if (!bytes) return { error };
  try {
    return { preview: await previewImport(book, bytes, mapChoice(formData)) };
  } catch (err) {
    return { error: message(err) };
  }
}

export async function commitTradebookAction(formData: FormData): Promise<CommitState> {
  const book = bookIdFromForm(formData);
  const sha = String(formData.get("file_sha256") ?? "");
  if (book == null) return { error: "Choose an imported book" };
  if (!/^[0-9a-f]{64}$/.test(sha)) return { error: "Preview the file before importing it" };
  const { bytes, error } = await fileBytes(formData);
  if (!bytes) return { error };
  try {
    const result = await commitImport(book, bytes, sha, mapChoice(formData));
    refresh();
    return { result };
  } catch (err) {
    return { error: message(err) };
  }
}

export async function deleteImportAction(
  _prev: ImportActionState,
  formData: FormData,
): Promise<ImportActionState> {
  const book = bookIdFromForm(formData);
  const batch = Number(formData.get("batch_id"));
  if (book == null || !Number.isSafeInteger(batch) || batch <= 0) {
    return { error: "That import is gone" };
  }
  try {
    await deleteImport(book, batch);
    refresh();
    return { ok: "Import deleted: its trades are gone and the book was rebuilt." };
  } catch (err) {
    return { error: message(err) };
  }
}

const LotSchema = z.object({
  // An NSE/BSE symbol in an INR book, a US one in a USD book: the API checks which.
  ticker: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z0-9&.-]{1,16}$/, "Use a symbol like TCS.NS (India) or AAPL (US)"),
  on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Pick the date the shares were held from"),
  quantity: z.coerce.number().positive("Quantity must be above zero").max(1e10),
  avg_price: z.coerce.number().positive("Average price must be above zero").max(1e9),
});

export async function addOpeningLotAction(
  _prev: ImportActionState,
  formData: FormData,
): Promise<ImportActionState> {
  const book = bookIdFromForm(formData);
  if (book == null) return { error: "Choose an imported book" };
  const parsed = LotSchema.safeParse({
    ticker: formData.get("ticker") ?? "",
    on: formData.get("on") ?? "",
    quantity: formData.get("quantity") ?? "",
    avg_price: formData.get("avg_price") ?? "",
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  try {
    const lot = await addOpeningLot(book, {
      ticker: parsed.data.ticker,
      on: parsed.data.on,
      quantity: String(parsed.data.quantity),
      avg_price: String(parsed.data.avg_price),
    });
    refresh();
    return {
      ok: `Opening lot added for ${lot.ticker}; waiting sells were posted where it covers them.`,
    };
  } catch (err) {
    return { error: message(err) };
  }
}

export async function deleteOpeningLotAction(
  _prev: ImportActionState,
  formData: FormData,
): Promise<ImportActionState> {
  const book = bookIdFromForm(formData);
  const lot = Number(formData.get("lot_id"));
  if (book == null || !Number.isSafeInteger(lot) || lot <= 0) return { error: "That lot is gone" };
  try {
    await deleteOpeningLot(book, lot);
    refresh();
    return { ok: "Opening lot removed." };
  } catch (err) {
    return { error: message(err) };
  }
}

const MapSchema = z.object({
  name: z.string().trim().min(1, "Name the map").max(60, "60 characters at most"),
  default_exchange: z.enum(["", "NSE", "BSE"]).transform((v) => (v === "" ? null : v)),
  date_order: z.enum(["auto", "day_first", "month_first"]),
});

/** A6.11: "Map columns yourself": save the user's choice of header per field. */
export async function saveImportMapAction(formData: FormData): Promise<SaveMapState> {
  const parsed = MapSchema.safeParse({
    name: formData.get("map_name") ?? "",
    default_exchange: formData.get("default_exchange") ?? "",
    date_order: formData.get("date_order") ?? "auto",
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  const mapping: Record<string, string> = {};
  for (const f of MAP_FIELDS) {
    const header = String(formData.get(`field_${f.field}`) ?? "").trim();
    if (header) mapping[f.field] = header.slice(0, 60);
  }
  const problem = mappingProblem(mapping);
  if (problem) return { error: problem };
  try {
    const saved = await saveImportMap({ ...parsed.data, mapping });
    revalidatePath("/portfolio/import");
    return { id: saved.id, name: saved.name };
  } catch (err) {
    return { error: message(err) };
  }
}

export async function deleteImportMapAction(
  _prev: ImportActionState,
  formData: FormData,
): Promise<ImportActionState> {
  const id = Number(formData.get("map_id"));
  if (!Number.isSafeInteger(id) || id <= 0) return { error: "That map is gone" };
  try {
    await deleteImportMap(id);
    revalidatePath("/portfolio/import");
    return { ok: "Map deleted." };
  } catch (err) {
    return { error: message(err) };
  }
}
