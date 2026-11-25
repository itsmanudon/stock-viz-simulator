"use server";

import { revalidatePath } from "next/cache";

import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import {
  type ColumnKey,
  type WatchlistColour,
  addToWatchlist,
  addWatchlistItems,
  createColumnSet,
  createWatchlist,
  deleteColumnSet,
  deleteWatchlist,
  listWatchlists,
  removeFromWatchlist,
  removeWatchlistItem,
  reorderWatchlists,
  updateColumnSet,
  updateWatchlist,
  updateWatchlistItem,
} from "@/lib/api/watchlist";
import { COLUMN_KEYS, LIST_COLOURS, moveListId, parseTagInput } from "@/lib/watchlist-columns";

export type WatchlistActionState = {
  error?: string;
  ticker?: string;
  inWatchlist?: boolean;
};

/** The result of the list, note, tag and column-set actions (A2.5). */
export type ListActionState = {
  ok?: boolean;
  error?: string;
  message?: string;
  /** A list created by the action, so the page can open it. */
  listId?: number;
};

function normalizeTicker(raw: FormDataEntryValue | null): string | null {
  if (typeof raw !== "string") return null;
  const t = raw.trim().toUpperCase();
  if (!t || t.length > 16) return null;
  return t;
}

function listIdOf(raw: FormDataEntryValue | null): number | null {
  if (typeof raw !== "string" || !/^\d+$/.test(raw)) return null;
  return Number(raw);
}

function apiMessage(err: AuthedApiError): string {
  try {
    const parsed = JSON.parse(err.detail) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      const first = parsed.detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
  } catch {
    // fall through
  }
  return err.detail || `API ${err.status}`;
}

async function run(work: () => Promise<ListActionState | undefined>): Promise<ListActionState> {
  try {
    const result = (await work()) ?? { ok: true };
    revalidatePath("/watchlist");
    revalidatePath("/dashboard");
    return { ok: true, ...result };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to use watchlists" };
    if (err instanceof AuthedApiError) return { error: apiMessage(err) };
    throw err;
  }
}

export async function toggleWatchlistAction(
  _prev: WatchlistActionState,
  formData: FormData,
): Promise<WatchlistActionState> {
  const ticker = normalizeTicker(formData.get("ticker"));
  if (!ticker) return { error: "Invalid ticker" };

  const wantOn = formData.get("intent") === "add";
  // A2.5: the /watchlist page names the open list; the stock page's star
  // and older forms act on the default list through /v1/watchlist.
  const listId = listIdOf(formData.get("watchlist_id"));

  try {
    if (listId !== null) {
      if (wantOn) {
        const result = await addWatchlistItems(listId, [ticker]);
        if (result.unknown.length) return { error: `Symbol ${ticker} not found` };
      } else {
        await removeWatchlistItem(listId, ticker);
      }
    } else if (wantOn) {
      await addToWatchlist(ticker);
    } else {
      await removeFromWatchlist(ticker);
    }
    revalidatePath("/watchlist");
    revalidatePath(`/stocks/${ticker}`);
    return { ticker, inWatchlist: wantOn };
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return { error: "Sign in to use the watchlist" };
    }
    if (err instanceof AuthedApiError) {
      // 404 on delete = already gone; treat as success.
      if (err.status === 404 && !wantOn) {
        revalidatePath("/watchlist");
        revalidatePath(`/stocks/${ticker}`);
        return { ticker, inWatchlist: false };
      }
      return { error: apiMessage(err) };
    }
    throw err;
  }
}

function colourOf(raw: FormDataEntryValue | null): WatchlistColour {
  const value = typeof raw === "string" ? raw : "";
  return (LIST_COLOURS.find((c) => c.key === value)?.key ?? "aqua") as WatchlistColour;
}

export async function createListAction(
  _prev: ListActionState,
  formData: FormData,
): Promise<ListActionState> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { error: "Give the list a name" };
  return run(async () => {
    const list = await createWatchlist(name, colourOf(formData.get("colour")));
    return { listId: list.id, message: `Created ${list.name}` };
  });
}

/** Rename and recolour a list (the fields sent). */
export async function updateListAction(
  _prev: ListActionState,
  formData: FormData,
): Promise<ListActionState> {
  const id = listIdOf(formData.get("watchlist_id"));
  if (id === null) return { error: "Unknown list" };
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { error: "Give the list a name" };
  return run(async () => {
    await updateWatchlist(id, { name, colour: colourOf(formData.get("colour")) });
    return { message: "Saved" };
  });
}

export async function makeDefaultListAction(id: number): Promise<ListActionState> {
  return run(async () => {
    await updateWatchlist(id, { is_default: true });
    return { message: "This is now your default list" };
  });
}

/** Move a list one place left (-1) or right (+1) in the tab order. */
export async function moveListAction(id: number, step: -1 | 1): Promise<ListActionState> {
  return run(async () => {
    const ids = (await listWatchlists()).map((list) => list.id);
    const next = moveListId(ids, id, step);
    if (next !== ids) await reorderWatchlists(next);
    return undefined;
  });
}

export async function deleteListAction(id: number): Promise<ListActionState> {
  return run(async () => {
    await deleteWatchlist(id);
    return { message: "List deleted" };
  });
}

export async function saveItemAction(
  listId: number,
  ticker: string,
  fields: { note?: string | null; tags?: string[] },
): Promise<ListActionState> {
  return run(async () => {
    await updateWatchlistItem(listId, ticker, fields);
    return undefined;
  });
}

/** Tags typed as "a, b, c" in a form field named `tags`. */
export async function saveTagsAction(
  _prev: ListActionState,
  formData: FormData,
): Promise<ListActionState> {
  const listId = listIdOf(formData.get("watchlist_id"));
  const ticker = normalizeTicker(formData.get("ticker"));
  if (listId === null || !ticker) return { error: "Unknown row" };
  return run(async () => {
    await updateWatchlistItem(listId, ticker, {
      tags: parseTagInput(String(formData.get("tags") ?? "")),
    });
    return undefined;
  });
}

/** The stock page's picker: put a ticker on, or take it off, one list. */
export async function setListMembershipAction(
  listId: number,
  ticker: string,
  on: boolean,
): Promise<ListActionState> {
  const symbol = normalizeTicker(ticker);
  if (!symbol) return { error: "Invalid ticker" };
  const result = await run(async () => {
    if (on) {
      const added = await addWatchlistItems(listId, [symbol]);
      if (added.unknown.length) return { error: `Symbol ${symbol} not found`, ok: false };
    } else {
      await removeWatchlistItem(listId, symbol);
    }
    return undefined;
  });
  revalidatePath(`/stocks/${symbol}`);
  return result;
}

/**
 * Bulk add from the screener: `tickers` (repeated or comma-separated) to the
 * list `watchlist_id`, or to a new list named `new_list`.
 */
export async function bulkAddAction(
  _prev: ListActionState,
  formData: FormData,
): Promise<ListActionState> {
  const tickers = [
    ...new Set(
      formData
        .getAll("tickers")
        .flatMap((value) => String(value).split(","))
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ),
  ];
  if (tickers.length === 0) return { error: "Tick at least one row first" };
  if (tickers.length > 100) return { error: "At most 100 symbols at a time" };
  const newName = String(formData.get("new_list") ?? "").trim();
  let listId = listIdOf(formData.get("watchlist_id"));
  return run(async () => {
    let created: number | undefined;
    if (listId === null) {
      if (!newName) return { error: "Pick a list or name a new one", ok: false };
      const list = await createWatchlist(newName, "aqua");
      listId = list.id;
      created = list.id;
    }
    const result = await addWatchlistItems(listId, tickers);
    const parts = [`Added ${result.added.length}`];
    if (result.already_listed.length) parts.push(`${result.already_listed.length} already listed`);
    if (result.unknown.length) parts.push(`${result.unknown.length} unknown`);
    return { message: `${parts.join(", ")}.`, listId: created ?? listId };
  });
}

function columnsOf(formData: FormData): ColumnKey[] {
  const allowed = new Set<string>(COLUMN_KEYS);
  return formData
    .getAll("columns")
    .map(String)
    .filter((key): key is ColumnKey => allowed.has(key));
}

/**
 * Save the column editor: update set `column_set_id` when given (and not
 * `save_as_new`), else create one; the list `watchlist_id` then uses it.
 */
export async function saveColumnSetAction(
  _prev: ListActionState,
  formData: FormData,
): Promise<ListActionState> {
  const columns = columnsOf(formData);
  if (columns.length === 0) return { error: "Pick at least one column" };
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { error: "Name the column set" };
  const setId = listIdOf(formData.get("column_set_id"));
  const listId = listIdOf(formData.get("watchlist_id"));
  const asNew = formData.get("save_as_new") === "1" || setId === null;
  return run(async () => {
    const saved = asNew
      ? await createColumnSet(name, columns)
      : await updateColumnSet(setId as number, { name, columns });
    if (listId !== null) await updateWatchlist(listId, { column_set_id: saved.id });
    return { message: `Saved ${saved.name}` };
  });
}

/** The picker: which saved set a list shows (null = the default columns). */
export async function chooseColumnSetAction(
  listId: number,
  setId: number | null,
): Promise<ListActionState> {
  return run(async () => {
    await updateWatchlist(listId, { column_set_id: setId });
    return undefined;
  });
}

export async function deleteColumnSetAction(setId: number): Promise<ListActionState> {
  return run(async () => {
    await deleteColumnSet(setId);
    return { message: "Column set deleted" };
  });
}
