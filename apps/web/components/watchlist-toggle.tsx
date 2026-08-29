"use client";

import { Star } from "lucide-react";
import { useActionState } from "react";

import {
  type WatchlistActionState,
  toggleWatchlistAction,
} from "@/app/(product)/(authed)/watchlist/actions";
import { Button } from "@/components/ui/button";

type Props = {
  ticker: string;
  initialInWatchlist: boolean;
  compact?: boolean;
};

export function WatchlistToggle({ ticker, initialInWatchlist, compact = false }: Props) {
  const [state, action, pending] = useActionState<WatchlistActionState, FormData>(
    toggleWatchlistAction,
    {},
  );

  const isOn =
    state.ticker === ticker && state.inWatchlist !== undefined
      ? state.inWatchlist
      : initialInWatchlist;

  return (
    <form action={action} className="inline-flex">
      <input type="hidden" name="ticker" value={ticker} />
      <input type="hidden" name="intent" value={isOn ? "remove" : "add"} />
      <Button
        type="submit"
        variant={isOn ? "default" : "outline"}
        size="sm"
        disabled={pending}
        aria-pressed={isOn}
        aria-label={isOn ? `Remove ${ticker} from watchlist` : `Add ${ticker} to watchlist`}
      >
        <Star className={`h-4 w-4 ${isOn ? "fill-current" : ""}`} aria-hidden />
        <span className="ml-1.5">
          {compact ? (isOn ? "Watching" : "Watch") : isOn ? "On watchlist" : "Add to watchlist"}
        </span>
      </Button>
    </form>
  );
}
