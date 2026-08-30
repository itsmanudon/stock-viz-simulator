"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState } from "react";

import { listSymbols, searchSymbols } from "@/lib/api/symbols";
import type { Symbol as SymbolRow } from "@/lib/api/types";
import {
  COMPARE_MAX_SYMBOLS,
  type CompareTimeframe,
  buildCompareHref,
} from "@/lib/compare-workspace";

type SearchFn = typeof searchSymbols;
type ListFn = () => Promise<SymbolRow[]>;

// The browse list is for scanning, not exhaustive paging — cap it so a
// multi-thousand-symbol universe doesn't render thousands of <li> nodes.
const BROWSE_CAP = 150;

export function CompareSymbolPicker({
  tickers,
  timeframe,
  names,
  watchlistTickers = [],
  search = searchSymbols,
  list = () => listSymbols(),
}: {
  tickers: string[];
  timeframe: CompareTimeframe;
  names: Record<string, string>;
  watchlistTickers?: string[];
  search?: SearchFn;
  list?: ListFn;
}) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [focused, setFocused] = useState(false);
  const [universe, setUniverse] = useState<SymbolRow[]>([]);
  const [universeStatus, setUniverseStatus] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  );
  const remaining = COMPARE_MAX_SYMBOLS - tickers.length;

  const selected = useMemo(() => new Set(tickers), [tickers]);

  function navigate(next: string[]) {
    router.push(buildCompareHref(next, timeframe));
  }

  async function loadUniverse() {
    if (universeStatus === "loading" || universeStatus === "ready") return;
    setUniverseStatus("loading");
    try {
      const rows = await list();
      setUniverse(rows);
      setUniverseStatus("ready");
    } catch {
      setUniverseStatus("error");
    }
  }

  async function onQuery(value: string) {
    setQuery(value);
    const needle = value.trim();
    if (!needle) {
      setResults([]);
      setStatus("idle");
      return;
    }
    setStatus("loading");
    try {
      const next = await search(needle, 8);
      setResults(next.filter((row) => !selected.has(row.ticker)));
      setStatus("ready");
    } catch {
      setResults([]);
      setStatus("error");
    }
  }

  function addTicker(ticker: string) {
    if (selected.has(ticker) || tickers.length >= COMPARE_MAX_SYMBOLS) return;
    setQuery("");
    setResults([]);
    setStatus("idle");
    navigate([...tickers, ticker]);
  }

  function removeTicker(ticker: string) {
    navigate(tickers.filter((item) => item !== ticker));
  }

  const trimmed = query.trim();
  // Typed → the restricted server search. Empty + focused → the full universe
  // to scroll through, minus what's already picked, capped for render weight.
  const browseRows = universe.filter((row) => !selected.has(row.ticker)).slice(0, BROWSE_CAP);
  const visibleRows = trimmed ? results : browseRows;
  const showDropdown =
    focused &&
    remaining > 0 &&
    (visibleRows.length > 0 || (!trimmed && universeStatus === "loading"));

  const watchlistPicks = watchlistTickers.filter((ticker) => !selected.has(ticker));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {tickers.map((ticker) => (
          <span
            key={ticker}
            className="inline-flex items-center gap-1 rounded-sm border border-border-muted bg-surface-secondary py-1 pr-1 pl-2 font-mono text-xs"
          >
            <span>{ticker}</span>
            <span className="hidden max-w-32 truncate text-text-tertiary sm:inline">
              {names[ticker] ?? ""}
            </span>
            <button
              type="button"
              onClick={() => removeTicker(ticker)}
              className="rounded-sm p-1 text-text-tertiary hover:bg-surface-hover hover:text-foreground"
              aria-label={`Remove ${ticker}`}
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
      </div>

      {watchlistPicks.length > 0 && remaining > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-text-tertiary">From your watchlist</span>
          {watchlistPicks.map((ticker) => (
            <button
              key={ticker}
              type="button"
              onClick={() => addTicker(ticker)}
              className="rounded-sm border border-border-muted px-1.5 py-0.5 font-mono hover:bg-surface-hover"
              title={names[ticker] ?? ticker}
            >
              + {ticker}
            </button>
          ))}
        </div>
      ) : null}

      <div className="relative max-w-md">
        <label htmlFor={listId} className="sr-only">
          Add a symbol to compare
        </label>
        <input
          id={listId}
          value={query}
          onChange={(event) => void onQuery(event.target.value)}
          onFocus={() => {
            setFocused(true);
            void loadUniverse();
          }}
          onBlur={() => setFocused(false)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && visibleRows[0]) {
              event.preventDefault();
              addTicker(visibleRows[0].ticker);
            }
          }}
          placeholder={
            remaining > 0 ? "Add ticker or company name" : "Maximum of 6 symbols reached"
          }
          disabled={remaining <= 0}
          className="h-9 w-full rounded-sm border border-input bg-background px-3 text-sm"
          autoComplete="off"
        />
        {status === "loading" ? (
          <p className="mt-1 text-xs text-text-tertiary">Searching…</p>
        ) : null}
        {status === "error" ? (
          <p className="mt-1 text-xs text-negative">Symbol search is unavailable.</p>
        ) : null}
        {showDropdown ? (
          <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-auto border border-border-muted bg-surface-elevated py-1 shadow-sm">
            {!trimmed && universeStatus === "loading" && browseRows.length === 0 ? (
              <li className="px-3 py-2 text-xs text-text-tertiary">Loading symbols…</li>
            ) : null}
            {visibleRows.map((row) => (
              <li key={row.ticker}>
                <button
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    addTicker(row.ticker);
                  }}
                  className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-surface-hover"
                >
                  <span className="min-w-[3.5rem] max-w-[9rem] shrink-0 truncate font-mono text-xs">
                    {row.ticker}
                  </span>
                  <span className="truncate text-text-secondary">{row.name}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
