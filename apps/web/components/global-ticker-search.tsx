"use client";

import { ArrowRight, Command, Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Dialog } from "radix-ui";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { searchSymbols } from "@/lib/api/symbols";
import type { Symbol as SymbolRow } from "@/lib/api/types";

type SearchFn = typeof searchSymbols;
type SearchStatus = "idle" | "loading" | "ready" | "error";

const POPULAR_SYMBOLS: SymbolRow[] = [
  {
    ticker: "AAPL",
    name: "Apple Inc.",
    sector: "Technology",
    exchange: "NASDAQ",
    currency: "USD",
    is_active: true,
  },
  {
    ticker: "MSFT",
    name: "Microsoft Corporation",
    sector: "Technology",
    exchange: "NASDAQ",
    currency: "USD",
    is_active: true,
  },
  {
    ticker: "NVDA",
    name: "NVIDIA Corporation",
    sector: "Technology",
    exchange: "NASDAQ",
    currency: "USD",
    is_active: true,
  },
  {
    ticker: "AMZN",
    name: "Amazon.com, Inc.",
    sector: "Consumer Cyclical",
    exchange: "NASDAQ",
    currency: "USD",
    is_active: true,
  },
];

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable
  );
}

export function GlobalTickerSearch({
  search = searchSymbols,
  debounceMs = 200,
}: {
  search?: SearchFn;
  debounceMs?: number;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const listboxId = useId();
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef(0);
  const wasOpenRef = useRef(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [open, setOpen] = useState(false);

  const openPalette = useCallback(() => {
    setOpen(true);
  }, []);

  const closePalette = useCallback(() => {
    setOpen(false);
    setActiveIndex(-1);
    triggerRef.current?.focus();
  }, []);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (nextOpen) {
        setOpen(true);
        return;
      }
      closePalette();
    },
    [closePalette],
  );

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      return;
    }
    if (!wasOpenRef.current) return;
    wasOpenRef.current = false;
    triggerRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openPalette();
        return;
      }
      if (
        event.key === "/" &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !isTypingTarget(event.target)
      ) {
        event.preventDefault();
        openPalette();
      }
    };

    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [openPalette]);

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
    closePalette();
    setQuery("");
    setResults([]);
    setStatus("idle");
    setActiveIndex(-1);
    const destination = new URLSearchParams();
    if (pathname.startsWith("/stocks/")) {
      const timeframe = searchParams.get("tf");
      if (timeframe) destination.set("tf", timeframe);
      if (searchParams.has("indicators")) {
        destination.set("indicators", searchParams.get("indicators") ?? "");
      }
    }
    const queryString = destination.toString();
    router.push(
      `/stocks/${encodeURIComponent(result.ticker)}${queryString ? `?${queryString}` : ""}`,
    );
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closePalette();
      return;
    }

    const navigableResults = hasQuery ? results : POPULAR_SYMBOLS;
    if (navigableResults.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % navigableResults.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => (current <= 0 ? navigableResults.length - 1 : current - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectResult(navigableResults[activeIndex]);
    }
  }

  const hasQuery = query.trim().length > 0;
  // Not gated on `open`: this list is a child of Radix Dialog.Content, which
  // stays mounted through its ~150ms close animation. Gating on `open` would
  // unmount the list the instant Escape is pressed, so it would vanish before
  // the surrounding panel finished animating out. Left ungated, both leave
  // together when Content unmounts.
  const expanded = hasQuery ? status !== "idle" : true;
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
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Trigger asChild>
        <button
          ref={triggerRef}
          type="button"
          // biome-ignore lint/a11y/useSemanticElements: the inline trigger preserves the existing combobox landmark while the editable combobox is portaled
          role="combobox"
          aria-label="Search tickers and companies"
          aria-expanded={open}
          aria-controls={listboxId}
          className="relative w-full text-left outline-none"
        >
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 z-10 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <span className="flex h-9 w-full items-center rounded-md border border-border-muted bg-surface-elevated py-1 pl-9 pr-16 text-sm text-text-tertiary transition-colors hover:border-ring/60 hover:text-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30">
            Search ticker or company
          </span>
          <kbd className="pointer-events-none absolute right-4 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded border bg-muted px-1.5 py-0.5 font-mono text-3xs text-muted-foreground sm:inline-flex">
            <Command className="size-3" aria-hidden /> K
          </kbd>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px] motion-reduce:backdrop-blur-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          aria-labelledby={titleId}
          className="fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[min(42rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-border bg-surface-elevated p-2 shadow-2xl outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 motion-reduce:animate-none"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            inputRef.current?.focus();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            triggerRef.current?.focus();
          }}
        >
          <Dialog.Title id={titleId} className="sr-only">
            Search StockViz
          </Dialog.Title>
          <Dialog.Description className="sr-only">
            Search for a stock by ticker or company name.
          </Dialog.Description>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-5 top-1/2 z-10 size-4 -translate-y-1/2 text-muted-foreground"
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
              className="h-12 w-full rounded-lg border border-border-muted bg-background py-1 pl-12 pr-20 text-base text-foreground outline-none placeholder:text-text-tertiary focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
            />
            <kbd className="pointer-events-none absolute right-4 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded border bg-muted px-1.5 py-0.5 font-mono text-3xs text-muted-foreground sm:inline-flex">
              <Command className="size-3" aria-hidden /> K
            </kbd>
          </div>

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
              className="mt-2 overflow-hidden rounded-xl border border-border bg-surface-elevated p-2 shadow-xl"
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
              {!hasQuery && status === "idle" ? (
                <>
                  <p className="px-3 pb-2 pt-1 text-2xs font-semibold tracking-[0.14em] text-text-tertiary uppercase">
                    Popular symbols
                  </p>
                  {POPULAR_SYMBOLS.map((result, index) => (
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
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-accent aria-selected:bg-accent"
                    >
                      <span className="w-16 shrink-0 font-mono font-semibold tabular-nums">
                        {result.ticker}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{result.name}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {result.exchange}
                      </span>
                    </button>
                  ))}
                  <div className="mt-2 grid gap-1 border-t border-border-muted px-3 pb-1 pt-3 text-xs text-text-tertiary sm:grid-cols-2">
                    <span className="inline-flex items-center gap-2">
                      <kbd className="rounded border px-1 py-0.5 font-mono text-3xs">↑↓</kbd>{" "}
                      Navigate
                    </span>
                    <span className="inline-flex items-center gap-2">
                      <kbd className="rounded border px-1 py-0.5 font-mono text-3xs">↵</kbd> Open
                      symbol
                    </span>
                    <span className="inline-flex items-center gap-2">
                      <kbd className="rounded border px-1 py-0.5 font-mono text-3xs">esc</kbd> Close
                      palette
                    </span>
                    <span className="inline-flex items-center gap-2">
                      <ArrowRight className="size-3" aria-hidden /> End-of-day prices
                    </span>
                  </div>
                </>
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
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-accent aria-selected:bg-accent"
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
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
