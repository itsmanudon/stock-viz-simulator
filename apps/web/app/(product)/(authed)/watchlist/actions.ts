"use server";

import { revalidatePath } from "next/cache";

import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { addToWatchlist, removeFromWatchlist } from "@/lib/api/watchlist";

export type WatchlistActionState = {
  error?: string;
  ticker?: string;
  inWatchlist?: boolean;
};

function normalizeTicker(raw: FormDataEntryValue | null): string | null {
  if (typeof raw !== "string") return null;
  const t = raw.trim().toUpperCase();
  if (!t || t.length > 16) return null;
  return t;
}

export async function toggleWatchlistAction(
  _prev: WatchlistActionState,
  formData: FormData,
): Promise<WatchlistActionState> {
  const ticker = normalizeTicker(formData.get("ticker"));
  if (!ticker) return { error: "Invalid ticker" };

  const wantOn = formData.get("intent") === "add";

  try {
    if (wantOn) {
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
      try {
        const parsed = JSON.parse(err.detail) as { detail?: string };
        if (parsed.detail) return { error: parsed.detail };
      } catch {
        // fall through
      }
      return { error: err.detail || `API ${err.status}` };
    }
    throw err;
  }
}
