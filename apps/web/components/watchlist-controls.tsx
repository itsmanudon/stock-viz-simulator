"use client";

import { MoreHorizontal } from "lucide-react";
import Link from "next/link";
import { useActionState } from "react";

import {
  type WatchlistActionState,
  toggleWatchlistAction,
} from "@/app/(product)/(authed)/watchlist/actions";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
          defaultValue={symbols[0]?.ticker}
        >
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

export function WatchlistRowActions({ ticker }: { ticker: string }) {
  const [, action, pending] = useActionState<WatchlistActionState, FormData>(
    toggleWatchlistAction,
    {},
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-sm"
          aria-label={`Actions for ${ticker}`}
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link href={`/stocks/${ticker}`}>Open research</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={buildTradeHref(ticker)}>Trade</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={buildAlertsHref({ ticker })}>Create alert</Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild variant="destructive">
          <form action={action}>
            <input type="hidden" name="ticker" value={ticker} />
            <input type="hidden" name="intent" value="remove" />
            <button type="submit" className="w-full text-left" disabled={pending}>
              {pending ? "Removing…" : "Remove from watchlist"}
            </button>
          </form>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
