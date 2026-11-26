"use client";

/**
 * The ⌘K / Ctrl+K command palette (A3.6), in the product top bar.
 *
 * - Opens with ⌘K or Ctrl+K anywhere in the product app (again to close), with
 *   `/` when focus is not in a field, or with the top-bar button (a full field
 *   from `sm`, an icon on phones).
 * - Searches pages and actions (`lib/command-palette.ts`, built from the one
 *   navigation map) as you type, and symbols through the global ticker search
 *   API. With no query it lists recent picks, suggestions for the current
 *   workspace and popular symbols.
 * - Keyboard: focus stays in the input (an ARIA combobox) and points at the
 *   active option with `aria-activedescendant`; ↑/↓ move and wrap, Enter opens,
 *   Escape closes and gives focus back to the trigger. Radix Dialog traps focus
 *   and makes the page behind inert.
 * - Book pages keep the current `?book=`; "Switch book…" opens the top bar's
 *   book switcher (`OPEN_BOOK_SWITCHER_EVENT`).
 * - Recent picks live in localStorage (`stockviz:palette-recent`), a
 *   convenience: every read and write is guarded.
 */

import { Command, CornerDownLeft, Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Dialog } from "radix-ui";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { NAV_ICONS } from "@/components/navigation-icons";
import { searchSymbols } from "@/lib/api/symbols";
import type { Symbol as SymbolRow } from "@/lib/api/types";
import { workspaceForPath } from "@/lib/app-navigation";
import { parseBookParam } from "@/lib/book-url";
import {
  OPEN_BOOK_SWITCHER_EVENT,
  type PaletteCommand,
  type RecentEntry,
  buildCommands,
  filterCommands,
  pushRecent,
  readRecents,
  resolveCommandHref,
  safeLocalStorage,
} from "@/lib/command-palette";
import { cn } from "@/lib/utils";

type SearchFn = typeof searchSymbols;
type SearchStatus = "idle" | "loading" | "ready" | "error";

export const POPULAR_SYMBOLS: SymbolRow[] = [
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

type SymbolOption = {
  kind: "symbol";
  key: string;
  ticker: string;
  name: string;
  exchange?: string | null;
};
type CommandOption = { kind: "command"; key: string; command: PaletteCommand };
type PaletteOption = SymbolOption | CommandOption;
type PaletteGroup = { id: string; label: string; options: PaletteOption[] };

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable
  );
}

function symbolOption(
  row: { ticker: string; name: string; exchange?: string | null },
  prefix: string,
): SymbolOption {
  return {
    kind: "symbol",
    key: `${prefix}:symbol:${row.ticker}`,
    ticker: row.ticker,
    name: row.name,
    exchange: row.exchange,
  };
}

function commandOption(command: PaletteCommand, prefix: string): CommandOption {
  return { kind: "command", key: `${prefix}:${command.id}`, command };
}

/** Suggestions with no query: the current workspace's other pages, then a few actions. */
function suggestions(commands: readonly PaletteCommand[], pathname: string): PaletteCommand[] {
  const workspace = workspaceForPath(pathname);
  const local = workspace
    ? commands.filter(
        (c) => c.kind === "page" && c.workspaceId === workspace.id && c.href !== pathname,
      )
    : [];
  const defaults = [
    "action:new-backtest",
    "page:/screener",
    "action:place-order",
    "action:switch-book",
  ]
    .map((id) => commands.find((c) => c.id === id))
    .filter((c): c is PaletteCommand => Boolean(c) && c?.href !== pathname);
  const picked: PaletteCommand[] = [];
  for (const command of [...local.slice(0, 3), ...defaults]) {
    if (!picked.some((c) => c.id === command.id)) picked.push(command);
  }
  return picked.slice(0, 5);
}

export function CommandPalette({
  signedIn = false,
  search = searchSymbols,
  debounceMs = 200,
}: {
  signedIn?: boolean;
  search?: SearchFn;
  debounceMs?: number;
}) {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const listboxId = useId();
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef(0);
  const afterCloseRef = useRef<(() => void) | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [activeIndex, setActiveIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const [recents, setRecents] = useState<RecentEntry[]>([]);

  const commands = useMemo(() => buildCommands({ signedIn }), [signedIn]);

  const closePalette = useCallback(() => setOpen(false), []);

  // Read recents each time the palette opens (another tab may have added some).
  // On close, give focus back to the trigger, or run the picked effect (the
  // book switcher takes focus itself).
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      setRecents(readRecents(safeLocalStorage()));
      return;
    }
    if (!wasOpenRef.current) return;
    wasOpenRef.current = false;
    const after = afterCloseRef.current;
    afterCloseRef.current = null;
    if (after) after();
    else triggerRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
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
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    const requestId = ++requestRef.current;
    setActiveIndex(0);

    if (!normalized) {
      setResults([]);
      setStatus("idle");
      return;
    }

    const timeout = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const next = await search(normalized, 6);
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

  const hasQuery = query.trim().length > 0;

  const groups: PaletteGroup[] = useMemo(() => {
    if (hasQuery) {
      const matched = filterCommands(commands, query);
      const out: PaletteGroup[] = [];
      if (matched.length > 0) {
        out.push({
          id: "commands",
          label: "Pages and Actions",
          options: matched.map((c) => commandOption(c, "q")),
        });
      }
      if (status === "ready" && results.length > 0) {
        out.push({
          id: "symbols",
          label: "Symbols",
          options: results.map((r) => symbolOption(r, "q")),
        });
      }
      return out;
    }
    const out: PaletteGroup[] = [];
    const recentOptions = recents
      .map((entry): PaletteOption | null => {
        if (entry.kind === "symbol") return symbolOption(entry, "recent");
        const command = commands.find((c) => c.id === entry.id);
        return command ? commandOption(command, "recent") : null;
      })
      .filter((o): o is PaletteOption => o !== null);
    if (recentOptions.length > 0)
      out.push({ id: "recent", label: "Recent", options: recentOptions });
    out.push({
      id: "suggested",
      label: "Suggested",
      options: suggestions(commands, pathname).map((c) => commandOption(c, "suggested")),
    });
    out.push({
      id: "popular",
      label: "Popular Symbols",
      options: POPULAR_SYMBOLS.map((r) => symbolOption(r, "popular")),
    });
    return out;
  }, [commands, hasQuery, pathname, query, recents, results, status]);

  const options = useMemo(() => groups.flatMap((g) => g.options), [groups]);
  const safeIndex = options.length === 0 ? -1 : Math.min(activeIndex, options.length - 1);
  const optionId = (index: number) => `${listboxId}-option-${index}`;

  useEffect(() => {
    if (safeIndex < 0) return;
    document
      .getElementById(`${listboxId}-option-${safeIndex}`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [safeIndex, listboxId]);

  function remember(entry: RecentEntry) {
    setRecents(pushRecent(safeLocalStorage(), entry));
  }

  function reset() {
    setQuery("");
    setResults([]);
    setStatus("idle");
    setActiveIndex(0);
  }

  function select(option: PaletteOption) {
    if (option.kind === "symbol") {
      remember({
        kind: "symbol",
        ticker: option.ticker,
        name: option.name,
        exchange: option.exchange,
      });
      const destination = new URLSearchParams();
      if (pathname.startsWith("/stocks/")) {
        const timeframe = searchParams?.get("tf");
        if (timeframe) destination.set("tf", timeframe);
        if (searchParams?.has("indicators")) {
          destination.set("indicators", searchParams.get("indicators") ?? "");
        }
      }
      const qs = destination.toString();
      closePalette();
      reset();
      router.push(`/stocks/${encodeURIComponent(option.ticker)}${qs ? `?${qs}` : ""}`);
      return;
    }
    const { command } = option;
    remember({ kind: "command", id: command.id });
    if (command.effect === "open-book-switcher") {
      // Open the switcher once the dialog has closed and returned focus.
      afterCloseRef.current = () => window.dispatchEvent(new Event(OPEN_BOOK_SWITCHER_EVENT));
      closePalette();
      reset();
      return;
    }
    const book = parseBookParam(searchParams?.get("book"));
    closePalette();
    reset();
    router.push(book == null ? command.href : resolveCommandHref(command.href, book));
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closePalette();
      return;
    }
    if (options.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((safeIndex + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex(safeIndex <= 0 ? options.length - 1 : safeIndex - 1);
    } else if (event.key === "Enter" && safeIndex >= 0) {
      event.preventDefault();
      select(options[safeIndex]);
    }
  }

  const statusMessage = hasQuery
    ? status === "loading"
      ? "Searching symbols"
      : status === "error"
        ? "Symbol search unavailable"
        : `${options.length} result${options.length === 1 ? "" : "s"}`
    : "";

  let runningIndex = -1;

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          ref={triggerRef}
          type="button"
          aria-label="Search symbols, pages and actions"
          aria-keyshortcuts="Meta+K Control+K /"
          data-palette-trigger
          className="group relative inline-flex size-10 shrink-0 items-center justify-center rounded-md text-left text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:block sm:size-auto sm:w-full sm:hover:bg-transparent sm:focus-visible:ring-0"
        >
          <Search
            className="pointer-events-none size-5 sm:absolute sm:left-3.5 sm:top-1/2 sm:z-10 sm:size-4 sm:-translate-y-1/2"
            aria-hidden
          />
          <span className="hidden h-9 w-full items-center rounded-md border border-border-muted bg-surface-elevated py-1 pl-9 pr-16 text-sm text-text-tertiary transition-colors hover:border-ring/60 hover:text-foreground sm:flex group-focus-visible:border-ring group-focus-visible:ring-2 group-focus-visible:ring-ring/30">
            <span className="truncate">Search symbols, pages, actions</span>
          </span>
          <kbd className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded border bg-muted px-1.5 py-0.5 font-mono text-3xs text-muted-foreground sm:inline-flex">
            <Command className="size-3" aria-hidden /> K
          </kbd>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px] motion-reduce:backdrop-blur-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          aria-labelledby={titleId}
          data-command-palette
          className="fixed top-3 left-1/2 z-50 flex max-h-[calc(100dvh-1.5rem)] w-[calc(100vw-1.5rem)] max-w-2xl -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-border bg-surface-elevated shadow-2xl outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 motion-reduce:animate-none sm:top-[12vh] sm:max-h-[min(36rem,80dvh)]"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            inputRef.current?.focus();
          }}
          onCloseAutoFocus={(event) => {
            // Focus is handed back by the effect on `open` below.
            event.preventDefault();
          }}
        >
          <Dialog.Title id={titleId} className="sr-only">
            Command palette
          </Dialog.Title>
          <Dialog.Description className="sr-only">
            Search for a symbol, a page or an action. Use the arrow keys to move through the
            results, Enter to open one and Escape to close.
          </Dialog.Description>
          <div className="relative border-b border-border-muted p-2">
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
              aria-label="Search symbols, pages and actions"
              aria-autocomplete="list"
              aria-controls={listboxId}
              aria-expanded={options.length > 0}
              aria-activedescendant={safeIndex >= 0 ? optionId(safeIndex) : undefined}
              placeholder="Search symbols, pages, actions"
              autoComplete="off"
              spellCheck={false}
              className="h-12 w-full rounded-lg border border-border-muted bg-background py-1 pl-10 pr-16 text-base text-foreground outline-none placeholder:text-text-tertiary focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
            />
            <kbd className="pointer-events-none absolute right-5 top-1/2 hidden -translate-y-1/2 rounded border bg-muted px-1.5 py-0.5 font-mono text-3xs text-muted-foreground sm:inline-flex">
              esc
            </kbd>
          </div>

          <span className="sr-only" aria-live="polite">
            {statusMessage}
          </span>

          <div
            id={listboxId}
            // biome-ignore lint/a11y/useSemanticElements: an async ARIA combobox needs a rich listbox, not a native select
            role="listbox"
            aria-label="Results"
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-y-auto p-2"
          >
            {groups.map((group) => {
              const labelId = `${listboxId}-${group.id}`;
              return (
                // biome-ignore lint/a11y/useSemanticElements: an option group inside an ARIA listbox
                <div key={group.id} role="group" aria-labelledby={labelId} className="pb-1">
                  <p
                    id={labelId}
                    className="px-3 pb-1.5 pt-2 text-2xs font-semibold tracking-[0.02em] text-text-tertiary"
                  >
                    {group.label}
                  </p>
                  {group.options.map((option) => {
                    runningIndex += 1;
                    const index = runningIndex;
                    return (
                      <PaletteRow
                        key={option.key}
                        id={optionId(index)}
                        option={option}
                        selected={index === safeIndex}
                        onHover={() => setActiveIndex(index)}
                        onSelect={() => select(option)}
                      />
                    );
                  })}
                </div>
              );
            })}
            {hasQuery && status === "loading" ? (
              <p className="px-3 py-3 text-sm text-muted-foreground">Searching symbols…</p>
            ) : null}
            {hasQuery && status === "error" ? (
              <p className="px-3 py-3 text-sm text-muted-foreground">Symbol search unavailable</p>
            ) : null}
            {hasQuery && status === "ready" && options.length === 0 ? (
              <p className="px-3 py-3 text-sm text-muted-foreground">
                No matching symbols, pages or actions
              </p>
            ) : null}
          </div>

          <div className="hidden items-center gap-4 border-t border-border-muted px-4 py-2 text-2xs text-text-tertiary sm:flex">
            <span className="inline-flex items-center gap-1.5">
              <kbd className="rounded border px-1 font-mono text-3xs">↑↓</kbd> Move
            </span>
            <span className="inline-flex items-center gap-1.5">
              <kbd className="rounded border px-1 font-mono text-3xs">↵</kbd> Open
            </span>
            <span className="inline-flex items-center gap-1.5">
              <kbd className="rounded border px-1 font-mono text-3xs">esc</kbd> Close
            </span>
            <span className="ml-auto">End-of-day prices</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PaletteRow({
  id,
  option,
  selected,
  onHover,
  onSelect,
}: {
  id: string;
  option: PaletteOption;
  selected: boolean;
  onHover: () => void;
  onSelect: () => void;
}) {
  const Icon = option.kind === "command" ? NAV_ICONS[option.command.iconHref] : null;
  return (
    <div
      id={id}
      // biome-ignore lint/a11y/useSemanticElements: focus stays on the combobox and points here with aria-activedescendant
      role="option"
      tabIndex={-1}
      aria-selected={selected}
      data-option-kind={option.kind === "symbol" ? "symbol" : option.command.kind}
      onMouseDown={(event) => event.preventDefault()}
      onMouseMove={onHover}
      onClick={onSelect}
      // Focus normally stays in the input, which owns the keyboard; this
      // covers an option focused some other way.
      onKeyDown={(event) => {
        if (event.key === "Enter") onSelect();
      }}
      className={cn(
        "flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm",
        selected && "bg-accent",
      )}
    >
      {option.kind === "symbol" ? (
        <>
          <span
            className="min-w-[3.5rem] max-w-[9rem] shrink-0 truncate ticker font-semibold tabular-nums"
            title={option.ticker}
          >
            {option.ticker}
          </span>
          <span className="min-w-0 flex-1 truncate">{option.name}</span>
          {option.exchange ? (
            <span className="shrink-0 text-xs text-muted-foreground">{option.exchange}</span>
          ) : null}
        </>
      ) : (
        <>
          <span className="grid size-5 shrink-0 place-items-center text-text-tertiary" aria-hidden>
            {Icon ? <Icon className={cn("size-4", selected && "text-brand")} /> : null}
          </span>
          <span className="min-w-0 flex-1 truncate">{option.command.label}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {option.command.hint}
            <span className="sr-only">
              {option.command.kind === "action" ? ", action" : ", page"}
            </span>
          </span>
        </>
      )}
      {selected ? (
        <CornerDownLeft
          className="hidden size-3.5 shrink-0 text-text-tertiary sm:block"
          aria-hidden
        />
      ) : null}
    </div>
  );
}
