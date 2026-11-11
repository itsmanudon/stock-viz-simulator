"use client";

import { ArrowLeftRight, Bell, LineChart, X } from "lucide-react";
import Link from "next/link";
import { useActionState } from "react";

import {
  type WatchlistActionState,
  toggleWatchlistAction,
} from "@/app/(product)/(authed)/watchlist/actions";
import { Button } from "@/components/ui/button";
import { buildAlertsHref, buildTradeHref } from "@/lib/operational-trading";

export function AddWatchlistForm({
  symbols,
}: {
  symbols: Array<{ ticker: string; name: string }>;
}) {
  const [state, action, pending] = useActionState<WatchlistActionState, FormData>(
    toggleWatchlistAction,
    {},
  );

  if (symbols.length === 0) {
    return (
      <p className="text-sm text-text-secondary">Every tracked symbol is already on this list.</p>
    );
  }

  return (
    <form action={action} className="flex flex-wrap items-end gap-2">
      <input type="hidden" name="intent" value="add" />
      <label className="min-w-[12rem] flex-1 text-xs">
        <span className="mb-1 block font-medium text-text-secondary">Add symbol</span>
        <select
          name="ticker"
          required
          className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 text-sm"
          // No preselected symbol: the first alphabetically (7203.T) had no
          // stored history and was added by a stray click (UI audit F2).
          defaultValue=""
        >
          <option value="" disabled>
            Choose a symbol
          </option>
          {symbols.map((symbol) => (
            <option key={symbol.ticker} value={symbol.ticker}>
              {symbol.ticker} — {symbol.name}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" size="sm" className="rounded-sm" disabled={pending}>
        {pending ? "Adding…" : "Add to watchlist"}
      </Button>
      {state.error ? (
        <p className="basis-full text-xs text-negative" role="alert">
          {state.error}
        </p>
      ) : null}
    </form>
  );
}

const ROW_ACTION =
  "inline-grid size-8 place-items-center rounded-full border border-border-muted text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring";

/**
 * A watched symbol's actions as four small round buttons (Aurora board v3),
 * in place of a "more" menu: research, trade, create an alert, remove. Each
 * has a spoken name and a tooltip, since the icon alone is not a label.
 */
export function WatchlistRowActions({ ticker }: { ticker: string }) {
  const [, action, pending] = useActionState<WatchlistActionState, FormData>(
    toggleWatchlistAction,
    {},
  );

  return (
    <div className="inline-flex items-center gap-1.5">
      <Link
        href={`/stocks/${ticker}`}
        className={ROW_ACTION}
        aria-label={`Open ${ticker} research`}
        title="Open research"
      >
        <LineChart className="size-3.5" aria-hidden />
      </Link>
      <Link
        href={buildTradeHref(ticker)}
        className={ROW_ACTION}
        aria-label={`Trade ${ticker}`}
        title="Trade"
      >
        <ArrowLeftRight className="size-3.5" aria-hidden />
      </Link>
      <Link
        href={buildAlertsHref({ ticker })}
        className={ROW_ACTION}
        aria-label={`Create an alert for ${ticker}`}
        title="Create alert"
      >
        <Bell className="size-3.5" aria-hidden />
      </Link>
      <form action={action}>
        <input type="hidden" name="ticker" value={ticker} />
        <input type="hidden" name="intent" value="remove" />
        <button
          type="submit"
          disabled={pending}
          className={`${ROW_ACTION} hover:border-negative/40 hover:text-negative disabled:opacity-50`}
          aria-label={pending ? `Removing ${ticker}` : `Remove ${ticker} from watchlist`}
          title="Remove from watchlist"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </form>
    </div>
  );
}
