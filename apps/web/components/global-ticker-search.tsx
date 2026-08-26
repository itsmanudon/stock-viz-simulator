"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { searchSymbols } from "@/lib/api/symbols";
import type { Symbol as SymbolRow } from "@/lib/api/types";

type SearchFn = typeof searchSymbols;
type SearchStatus = "idle" | "loading" | "ready" | "error";

export function GlobalTickerSearch({
  search = searchSymbols,
  debounceMs = 200,
}: {
  search?: SearchFn;
  debounceMs?: number;
}) {
  const router = useRouter();
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef(0);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [status, setStatus] = useState<SearchStatus>("idle");

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };

    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    const requestId = ++requestRef.current;
    setActiveIndex(-1);

    if (!normalized) {
      setResults([]);
      setStatus("idle");
      return;
    }

    const timeout = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const next = await search(normalized, 8);
        if (requestRef.current !== requestId) return;
        setResults(next);
        setStatus("ready");
      } catch {
        if (requestRef.current !== requestId) return;
        setResults([]);
        setStatus("error");
      }
    }, debounceMs);

    return () => window.clearTimeout(timeout);
  }, [debounceMs, query, search]);

  function selectResult(result: SymbolRow) {
    setQuery("");
    setResults([]);
    setStatus("idle");
    setActiveIndex(-1);
    router.push(`/stocks/${encodeURIComponent(result.ticker)}`);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setResults([]);
      setStatus("idle");
      setActiveIndex(-1);
      return;
    }

    if (results.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => (current <= 0 ? results.length - 1 : current - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectResult(results[activeIndex]);
    }
  }

  const hasQuery = query.trim().length > 0;
  const expanded = hasQuery && status !== "idle";
  const activeOptionId = activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined;
  const statusMessage =
    status === "loading"
      ? "Searching symbols"
      : status === "error"
        ? "Search unavailable"
        : status === "ready"
          ? `${results.length} result${results.length === 1 ? "" : "s"}`
          : "";

  return (
    <div className="relative w-full">
      <Search
        className="pointer-events-none absolute left-3 top-1/2 z-10 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <input
        ref={inputRef}
        type="search"
        role="combobox"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
        aria-label="Search tickers and companies"
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={expanded}
        aria-activedescendant={activeOptionId}
        placeholder="Search ticker or company"
        autoComplete="off"
        className="h-9 w-full rounded-md border border-input bg-surface-elevated py-1 pl-9 pr-16 text-sm text-foreground outline-none placeholder:text-text-tertiary focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
      />
      <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 items-center rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:inline-flex">
        Ctrl K
      </kbd>

      <span className="sr-only" aria-live="polite">
        {statusMessage}
      </span>

      {expanded ? (
        <div
          id={listboxId}
          // biome-ignore lint/a11y/useSemanticElements: an async ARIA combobox needs a rich listbox, not a native select
          role="listbox"
          tabIndex={-1}
          aria-label="Ticker search results"
          className="absolute left-0 right-0 top-[calc(100%+0.375rem)] z-50 overflow-hidden rounded-md border border-border-muted bg-popover p-1 shadow-lg"
        >
          {status === "loading" ? (
            <p className="px-3 py-3 text-sm text-muted-foreground">Searching…</p>
          ) : null}
          {status === "error" ? (
            <p className="px-3 py-3 text-sm text-muted-foreground">Search unavailable</p>
          ) : null}
          {status === "ready" && results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-muted-foreground">No matching symbols</p>
          ) : null}
          {status === "ready"
            ? results.map((result, index) => (
                <button
                  key={result.ticker}
                  id={`${listboxId}-${index}`}
                  type="button"
                  // biome-ignore lint/a11y/useSemanticElements: focus stays on the combobox and points here with aria-activedescendant
                  role="option"
                  aria-selected={activeIndex === index}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    selectResult(result);
                  }}
                  onMouseEnter={() => setActiveIndex(index)}
                  className="flex w-full items-center gap-3 rounded-sm px-3 py-2 text-left text-sm hover:bg-accent aria-selected:bg-accent"
                >
                  <span className="w-16 shrink-0 font-mono font-semibold tabular-nums">
                    {result.ticker}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{result.name}</span>
                  {result.exchange ? (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {result.exchange}
                    </span>
                  ) : null}
                </button>
              ))
            : null}
        </div>
      ) : null}
    </div>
  );
}
