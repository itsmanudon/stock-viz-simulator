"use client";

import { ArrowLeft, Check, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SignalRow, SignalSortDir, SignalSortKey } from "@/lib/signals-workspace";
import { SIGNAL_MAX_SCORE, formatSignalDate, formatSignalDateTime } from "@/lib/signals-workspace";
import { cn } from "@/lib/utils";

function ariaSort(active: boolean, dir: SignalSortDir): "ascending" | "descending" | "none" {
  if (!active) return "none";
  return dir === "asc" ? "ascending" : "descending";
}

function sortLabel(key: SignalSortKey): string {
  switch (key) {
    case "ticker":
      return "Ticker";
    case "sentiment":
      return "Sentiment";
    case "updated":
      return "Updated";
    default:
      return "Strength";
  }
}

const SIGNAL_DETAIL_TRANSITION_MS = 300;

export function SignalsTable({
  rows,
  sort,
  dir,
  sortHrefs,
  initialSelectedTicker,
}: {
  rows: SignalRow[];
  sort: SignalSortKey;
  dir: SignalSortDir;
  sortHrefs: Record<SignalSortKey, string>;
  initialSelectedTicker?: string;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const knownTickers = useMemo(() => new Set(rows.map((row) => row.ticker)), [rows]);
  const selectedFromUrl = searchParams.get("selected")?.trim().toUpperCase() || null;
  const initialSelection =
    initialSelectedTicker && knownTickers.has(initialSelectedTicker) ? initialSelectedTicker : null;
  const [selectedTicker, setSelectedTicker] = useState<string | null>(initialSelection);
  const [detailTicker, setDetailTicker] = useState<string | null>(initialSelection);
  const selectedButtonRef = useRef<HTMLButtonElement | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const expectedSelectionRef = useRef<string | null | undefined>(undefined);
  const [isClosing, setIsClosing] = useState(false);

  const selectedRow = selectedTicker
    ? (rows.find((row) => row.ticker === selectedTicker) ?? null)
    : null;
  const detailRow = detailTicker ? (rows.find((row) => row.ticker === detailTicker) ?? null) : null;

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current === null) return;
    clearTimeout(closeTimerRef.current);
    closeTimerRef.current = null;
  }, []);

  const openDetail = useCallback(
    (next: string) => {
      setIsClosing(false);
      clearCloseTimer();
      setDetailTicker((current) => (current === next ? current : next));
      setSelectedTicker((current) => (current === next ? current : next));
    },
    [clearCloseTimer],
  );

  const closeDetail = useCallback(() => {
    if (selectedTicker === null) {
      setDetailTicker(null);
      setIsClosing(false);
      return;
    }

    setIsClosing(true);
    if (!detailTicker) {
      setDetailTicker(null);
      setSelectedTicker(null);
      return;
    }

    if (closeTimerRef.current !== null) return;
    closeTimerRef.current = setTimeout(() => {
      closeTimerRef.current = null;
      setIsClosing(false);
      setDetailTicker(null);
      setSelectedTicker(null);
    }, SIGNAL_DETAIL_TRANSITION_MS);
  }, [detailTicker, selectedTicker]);

  const syncSelectionFromUrl = useCallback(
    (rawTicker: string | null) => {
      const next = rawTicker?.trim().toUpperCase() || null;
      // Native history updates can briefly render with the previous
      // useSearchParams snapshot. Ignore that stale render after an explicit
      // selection change; the subsequent URL-backed render remains the source
      // of truth for browser back/forward and shared links.
      if (expectedSelectionRef.current !== undefined) {
        if (expectedSelectionRef.current !== next) return;
        expectedSelectionRef.current = undefined;
      }

      if (next && knownTickers.has(next)) {
        openDetail(next);
      } else {
        // Invalid or filtered-out tickers deliberately resolve to the scan view.
        closeDetail();
      }
    },
    [closeDetail, knownTickers, openDetail],
  );

  // Search params are the source of truth for shared links and Next-integrated
  // native history changes. Invalid or filtered-out tickers resolve to the scan view.
  useEffect(() => {
    syncSelectionFromUrl(selectedFromUrl);
  }, [selectedFromUrl, syncSelectionFromUrl]);

  // Keep an explicit popstate listener as a fallback for browser back/forward
  // and history implementations that do not trigger a render synchronously.
  useEffect(() => {
    function onPopState() {
      // A browser back/forward navigation is authoritative and supersedes a
      // pending native-history update from the last click.
      expectedSelectionRef.current = undefined;
      syncSelectionFromUrl(new URLSearchParams(window.location.search).get("selected"));
    }

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [syncSelectionFromUrl]);

  useEffect(() => () => clearCloseTimer(), [clearCloseTimer]);

  const updateSelection = useCallback(
    (next: string | null) => {
      expectedSelectionRef.current = next;
      if (next) {
        openDetail(next);
      } else {
        closeDetail();
      }

      if (typeof window === "undefined") return;
      // Read the live URL so rapid interactions never overwrite filters or
      // sorting with a stale useSearchParams snapshot.
      const params = new URLSearchParams(window.location.search);
      if (next) {
        params.set("selected", next);
        const query = params.toString();
        window.history.pushState(null, "", `${pathname}?${query}${window.location.hash}`);
      } else {
        params.delete("selected");
        const query = params.toString();
        window.history.replaceState(
          null,
          "",
          `${query ? `${pathname}?${query}` : pathname}${window.location.hash}`,
        );
      }
    },
    [closeDetail, openDetail, pathname],
  );

  function handleSelect(row: SignalRow) {
    if (row.ticker === selectedTicker) return;
    selectedButtonRef.current = document.querySelector<HTMLButtonElement>(
      `[data-signal-ticker="${CSS.escape(row.ticker)}"]`,
    );
    updateSelection(row.ticker);
  }

  const handleClose = useCallback(() => {
    const focusTarget = selectedButtonRef.current;
    updateSelection(null);
    requestAnimationFrame(() => focusTarget?.focus());
  }, [updateSelection]);

  useEffect(() => {
    if (!selectedRow) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        handleClose();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleClose, selectedRow]);

  return (
    <div
      className={cn(
        "min-w-0 lg:grid lg:h-[calc(100dvh-13rem)] lg:min-h-[36rem] lg:max-h-[calc(100dvh-13rem)] lg:grid-rows-[minmax(0,1fr)] lg:items-stretch lg:overflow-hidden motion-reduce:transition-none",
        selectedRow
          ? "lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]"
          : "lg:grid-cols-[minmax(0,1fr)_minmax(0,0fr)]",
      )}
    >
      <div className={cn("min-w-0 lg:min-h-0", selectedRow && "hidden lg:block")}>
        <SignalsList
          rows={rows}
          selectedTicker={selectedTicker}
          sort={sort}
          dir={dir}
          sortHrefs={sortHrefs}
          onSelect={handleSelect}
        />
      </div>

      <div
        className={cn(
          "min-w-0 overflow-hidden transition-opacity duration-300 ease-out motion-reduce:transition-none",
          detailRow
            ? isClosing
              ? "opacity-0 pointer-events-none"
              : "opacity-100 lg:pointer-events-auto"
            : selectedRow
              ? "pointer-events-none opacity-0 max-lg:hidden"
              : "pointer-events-none hidden opacity-0 lg:block",
        )}
      >
        {detailRow ? (
          <SignalDetail key={detailRow.ticker} row={detailRow} onClose={handleClose} />
        ) : null}
      </div>
    </div>
  );
}

function SignalsList({
  rows,
  selectedTicker,
  sort,
  dir,
  sortHrefs,
  onSelect,
}: {
  rows: SignalRow[];
  selectedTicker: string | null;
  sort: SignalSortKey;
  dir: SignalSortDir;
  sortHrefs: Record<SignalSortKey, string>;
  onSelect: (row: SignalRow) => void;
}) {
  const collapsed = Boolean(selectedTicker);

  return (
    <section
      aria-label="Signals list"
      className={cn(
        "flex h-full min-h-0 min-w-0 flex-col",
        collapsed
          ? "border-y border-border-muted bg-card lg:border lg:border-r-0"
          : "border-y border-border-muted bg-card",
      )}
    >
      {collapsed ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-muted px-3 py-2.5">
          <div>
            <p className="text-xs font-semibold">Signals</p>
            <p className="mt-0.5 text-2xs text-text-tertiary">{rows.length} tracked</p>
          </div>
          <SignalSortLinks sort={sort} dir={dir} sortHrefs={sortHrefs} compact />
        </div>
      ) : (
        <table className="hidden w-full table-fixed border-b border-border-muted text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase md:table">
          <thead>
            <tr>
              <SignalColumnHeader
                label="Ticker"
                sort="ticker"
                activeSort={sort}
                dir={dir}
                href={sortHrefs.ticker}
                className="w-[12%]"
              />
              <th scope="col" className="w-[26%] px-3 py-2.5">
                Company
              </th>
              <th scope="col" className="w-[12%] px-3 py-2.5">
                Signal
              </th>
              <SignalColumnHeader
                label="Strength"
                sort="score"
                activeSort={sort}
                dir={dir}
                href={sortHrefs.score}
                className="w-[11%]"
              />
              <th scope="col" className="w-[13%] px-3 py-2.5">
                Supporting votes
              </th>
              <SignalColumnHeader
                label="Sentiment"
                sort="sentiment"
                activeSort={sort}
                dir={dir}
                href={sortHrefs.sentiment}
                className="w-[12%]"
              />
              <SignalColumnHeader
                label="Updated"
                sort="updated"
                activeSort={sort}
                dir={dir}
                href={sortHrefs.updated}
                className="w-[14%]"
              />
            </tr>
          </thead>
        </table>
      )}

      <ul className={cn("min-h-0 divide-y divide-border-muted lg:flex-1 lg:overflow-y-auto")}>
        {rows.map((row) => (
          <li key={row.ticker}>
            <SignalRowButton
              row={row}
              selected={selectedTicker === row.ticker}
              collapsed={collapsed}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SignalSortLinks({
  sort,
  dir,
  sortHrefs,
  compact = false,
}: {
  sort: SignalSortKey;
  dir: SignalSortDir;
  sortHrefs: Record<SignalSortKey, string>;
  compact?: boolean;
}) {
  const options: SignalSortKey[] = ["score", "ticker", "sentiment", "updated"];
  return (
    <nav
      aria-label="Signal sorting"
      className={cn("flex flex-wrap items-center gap-1.5", compact && "gap-1")}
    >
      <span className="text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
        Sort
      </span>
      {options.map((key) => (
        <Link
          key={key}
          href={sortHrefs[key]}
          aria-current={sort === key ? "true" : undefined}
          className={cn(
            "rounded-sm px-1.5 py-1 text-2xs transition-colors hover:bg-surface-hover hover:text-foreground",
            sort === key ? "font-semibold text-brand" : "text-text-tertiary",
          )}
        >
          {sortLabel(key)}
          {sort === key ? <span aria-hidden> {dir === "asc" ? "↑" : "↓"}</span> : null}
        </Link>
      ))}
    </nav>
  );
}

function SignalColumnHeader({
  label,
  sort,
  activeSort,
  dir,
  href,
  className,
}: {
  label: string;
  sort: SignalSortKey;
  activeSort: SignalSortKey;
  dir: SignalSortDir;
  href: string;
  className?: string;
}) {
  return (
    <th
      scope="col"
      aria-sort={ariaSort(activeSort === sort, dir)}
      className={cn("px-3 py-2.5", className)}
    >
      <Link href={href} className="hover:text-foreground">
        {label}
      </Link>
    </th>
  );
}

function SignalRowButton({
  row,
  selected,
  collapsed,
  onSelect,
}: {
  row: SignalRow;
  selected: boolean;
  collapsed: boolean;
  onSelect: (row: SignalRow) => void;
}) {
  return (
    <button
      type="button"
      data-signal-ticker={row.ticker}
      aria-label={`${row.ticker}, ${row.name}, ${row.signal}, strength ${row.score} of ${SIGNAL_MAX_SCORE}`}
      aria-pressed={selected}
      onClick={() => onSelect(row)}
      className={cn(
        "w-full text-left outline-none transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        selected && "bg-brand-muted/50",
        collapsed
          ? "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-3"
          : "grid grid-cols-[minmax(4.5rem,0.7fr)_minmax(0,1fr)_minmax(4.5rem,0.7fr)] items-center md:grid-cols-[minmax(5rem,0.7fr)_minmax(0,1.5fr)_minmax(5.5rem,0.7fr)_minmax(4.5rem,0.6fr)_minmax(6rem,0.7fr)_minmax(5.5rem,0.65fr)_minmax(7rem,0.8fr)]",
      )}
    >
      {collapsed ? (
        <span className="min-w-0">
          <span className="flex min-w-0 items-center gap-2">
            <span className="font-mono text-sm font-semibold">{row.ticker}</span>
            <SignalBadge signal={row.signal} />
          </span>
          <span className="mt-1 block truncate text-xs text-text-secondary">{row.name}</span>
          <span className="mt-1 block text-2xs text-text-tertiary">
            {row.supportingVotes} supporting checks
          </span>
        </span>
      ) : (
        <>
          <span className="min-w-0 px-3 py-3 font-mono font-medium">
            {row.ticker}
            <span className="mt-0.5 block truncate text-xs text-text-secondary md:hidden">
              {row.name}
            </span>
          </span>
          <span className="hidden truncate px-3 py-3 text-text-secondary md:block">{row.name}</span>
          <span className="px-3 py-3">
            <SignalBadge signal={row.signal} />
          </span>
          <span className="px-3 py-3 font-mono tabular-nums">
            {row.score}/{SIGNAL_MAX_SCORE}
          </span>
          <span className="hidden px-3 py-3 font-mono text-xs tabular-nums md:block">
            {row.supportingVotes} / {SIGNAL_MAX_SCORE}
          </span>
          <span className="hidden px-3 py-3 font-mono text-xs tabular-nums lg:block">
            {row.sentiment7d === null
              ? "—"
              : `${row.sentiment7d > 0 ? "+" : ""}${row.sentiment7d.toFixed(2)}`}
          </span>
          <span className="hidden px-3 py-3 text-xs text-text-tertiary sm:block">
            {formatSignalDate(row.computedAt)}
          </span>
        </>
      )}
      {collapsed ? (
        <span className="text-right">
          <span className="block font-mono text-base font-semibold tabular-nums">
            {row.score}/{SIGNAL_MAX_SCORE}
          </span>
          <span className="mt-0.5 block text-2xs text-text-tertiary">strength</span>
        </span>
      ) : null}
    </button>
  );
}

function SignalBadge({ signal }: { signal: SignalRow["signal"] }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-2xs font-semibold tracking-wide uppercase",
        signal === "bullish"
          ? "bg-positive/15 text-positive"
          : "bg-surface-secondary text-text-secondary",
      )}
    >
      {signal === "bullish" ? "Bullish" : "Neutral"}
    </span>
  );
}

function SignalDetail({ row, onClose }: { row: SignalRow; onClose: () => void }) {
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const detailId = `signal-detail-${row.ticker}`;

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <section
      aria-labelledby={detailId}
      className="animate-in fade-in-0 flex h-full min-h-0 min-w-0 flex-col border border-border-muted bg-card duration-200 motion-reduce:animate-none"
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border-muted px-4 py-3 sm:px-6">
        <p className="text-3xs font-semibold tracking-[0.14em] text-text-tertiary uppercase">
          Signal detail
        </p>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex items-center gap-1.5 rounded-sm px-2 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Back to signals
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6 lg:max-h-none">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-sm font-semibold tracking-wide text-brand">{row.ticker}</p>
            <h2
              id={detailId}
              ref={headingRef}
              tabIndex={-1}
              className="mt-1 text-2xl font-semibold tracking-tight outline-none sm:text-3xl"
            >
              {row.name}
            </h2>
            <p className="mt-2 text-sm text-text-secondary">
              {row.sector ? `${row.sector} · ` : ""}Rule-based signal evidence
            </p>
          </div>
          <SignalBadge signal={row.signal} />
        </div>

        <dl className="mt-6 grid grid-cols-2 divide-x divide-border-muted border-y border-border-muted sm:grid-cols-3">
          <div className="py-3 pr-3 sm:pr-5">
            <dt className="text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
              Strength
            </dt>
            <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">
              {row.score}/{SIGNAL_MAX_SCORE}
            </dd>
          </div>
          <div className="border-t border-border-muted py-3 pl-3 sm:border-t-0 sm:px-5">
            <dt className="text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
              Supporting votes
            </dt>
            <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">
              {row.supportingVotes}/{SIGNAL_MAX_SCORE}
            </dd>
          </div>
          <div className="col-span-2 border-t border-border-muted py-3 sm:col-span-1 sm:border-t-0 sm:pl-5">
            <dt className="text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
              7-day sentiment
            </dt>
            <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">
              {row.sentiment7d === null
                ? "—"
                : `${row.sentiment7d > 0 ? "+" : ""}${row.sentiment7d.toFixed(2)}`}
            </dd>
          </div>
        </dl>

        <div className="mt-6 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold">Seven vote checks</h3>
            <p className="mt-1 text-xs text-text-secondary">
              The engine&apos;s checks are shown exactly as pass/fail evidence, not as an AI
              opinion.
            </p>
          </div>
          <time dateTime={row.computedAt} className="text-2xs text-text-tertiary">
            Computed {formatSignalDateTime(row.computedAt)}
          </time>
        </div>

        <ol className="mt-3 divide-y divide-border-muted border-y border-border-muted">
          {row.votes.map((vote) => (
            <li key={vote.id} className="flex gap-3 py-3">
              <span
                className={cn(
                  "inline-flex h-6 min-w-[4.5rem] shrink-0 items-center justify-center gap-1 rounded-sm px-1.5 text-2xs font-semibold",
                  vote.passed
                    ? "bg-positive-soft text-positive-soft-foreground"
                    : "bg-negative-soft text-negative-soft-foreground",
                )}
              >
                {vote.passed ? (
                  <Check className="size-3" aria-hidden />
                ) : (
                  <X className="size-3" aria-hidden />
                )}
                {vote.passed ? "Passed" : "Not passed"}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{vote.label}</span>
                <span className="mt-0.5 block text-xs leading-5 text-text-secondary">
                  {vote.detail}
                </span>
              </span>
            </li>
          ))}
        </ol>

        <nav
          aria-label={`${row.ticker} research actions`}
          className="mt-5 flex flex-wrap gap-x-4 gap-y-2 text-xs"
        >
          <Link href={`/stocks/${row.ticker}`} className="font-medium text-brand hover:underline">
            Open {row.ticker} workspace
          </Link>
          <Link
            href={`/backtest?ticker=${row.ticker}`}
            className="text-text-secondary hover:underline"
          >
            Backtest {row.ticker}
          </Link>
          <Link
            href={`/compare?tickers=${row.ticker}`}
            className="text-text-secondary hover:underline"
          >
            Compare {row.ticker}
          </Link>
          <Link
            href={`/trade?ticker=${row.ticker}`}
            className="text-text-secondary hover:underline"
          >
            Trade {row.ticker}
          </Link>
        </nav>
      </div>
    </section>
  );
}
