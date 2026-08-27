"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState } from "react";

import { searchSymbols } from "@/lib/api/symbols";
import type { Symbol as SymbolRow } from "@/lib/api/types";
import {
  COMPARE_MAX_SYMBOLS,
  type CompareTimeframe,
  buildCompareHref,
} from "@/lib/compare-workspace";

type SearchFn = typeof searchSymbols;

export function CompareSymbolPicker({
  tickers,
  timeframe,
  names,
  search = searchSymbols,
}: {
  tickers: string[];
  timeframe: CompareTimeframe;
  names: Record<string, string>;
  search?: SearchFn;
}) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const remaining = COMPARE_MAX_SYMBOLS - tickers.length;

  const selected = useMemo(() => new Set(tickers), [tickers]);

  function navigate(next: string[]) {
    router.push(buildCompareHref(next, timeframe));
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

      <div className="relative max-w-md">
        <label htmlFor={listId} className="sr-only">
          Add a symbol to compare
        </label>
        <input
          id={listId}
          value={query}
          onChange={(event) => void onQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && results[0]) {
              event.preventDefault();
              addTicker(results[0].ticker);
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
        {results.length > 0 ? (
          <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-auto border border-border-muted bg-surface-elevated py-1 shadow-sm">
            {results.map((row) => (
              <li key={row.ticker}>
                <button
                  type="button"
                  onClick={() => addTicker(row.ticker)}
                  className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-surface-hover"
                >
                  <span className="font-mono text-xs">{row.ticker}</span>
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
