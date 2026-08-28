import Link from "next/link";

import type { SignalRow, SignalSortDir, SignalSortKey } from "@/lib/signals-workspace";
import { SIGNAL_MAX_SCORE, formatSignalDate } from "@/lib/signals-workspace";
import { cn } from "@/lib/utils";

function ariaSort(active: boolean, dir: SignalSortDir): "ascending" | "descending" | "none" {
  if (!active) return "none";
  return dir === "asc" ? "ascending" : "descending";
}

export function SignalsTable({
  rows,
  sort,
  dir,
  sortHref,
}: {
  rows: SignalRow[];
  sort: SignalSortKey;
  dir: SignalSortDir;
  sortHref: (key: SignalSortKey) => string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[48rem] text-sm">
        <caption className="sr-only">
          Explainable market signals for the tracked universe. Expand a row for vote evidence.
        </caption>
        <thead>
          <tr className="border-y border-border-muted text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
            <th scope="col" className="px-3 py-2.5" aria-sort={ariaSort(sort === "ticker", dir)}>
              <a href={sortHref("ticker")} className="hover:text-foreground">
                Ticker
              </a>
            </th>
            <th scope="col" className="px-3 py-2.5">
              Company
            </th>
            <th scope="col" className="px-3 py-2.5">
              Signal
            </th>
            <th scope="col" className="px-3 py-2.5" aria-sort={ariaSort(sort === "score", dir)}>
              <a href={sortHref("score")} className="hover:text-foreground">
                Strength
              </a>
            </th>
            <th scope="col" className="hidden px-3 py-2.5 md:table-cell">
              Supporting votes
            </th>
            <th
              scope="col"
              className="hidden px-3 py-2.5 lg:table-cell"
              aria-sort={ariaSort(sort === "sentiment", dir)}
            >
              <a href={sortHref("sentiment")} className="hover:text-foreground">
                Sentiment
              </a>
            </th>
            <th
              scope="col"
              className="hidden px-3 py-2.5 sm:table-cell"
              aria-sort={ariaSort(sort === "updated", dir)}
            >
              <a href={sortHref("updated")} className="hover:text-foreground">
                Updated
              </a>
            </th>
          </tr>
        </thead>
        {rows.map((row) => (
          <tbody key={row.ticker} className="border-b border-border-muted">
            <tr>
              <td colSpan={7} className="p-0">
                <details className="group">
                  <summary className="grid cursor-pointer grid-cols-[minmax(4.5rem,0.7fr)_minmax(0,1.4fr)_minmax(5.5rem,0.7fr)_minmax(4.5rem,0.6fr)] items-center gap-0 px-0 py-0 marker:content-none md:grid-cols-[minmax(4.5rem,0.7fr)_minmax(0,1.4fr)_minmax(5.5rem,0.7fr)_minmax(4.5rem,0.6fr)_minmax(6rem,0.7fr)_minmax(5rem,0.6fr)_minmax(6rem,0.7fr)]">
                    <span className="px-3 py-3 font-mono font-medium">{row.ticker}</span>
                    <span className="truncate px-3 py-3 text-text-secondary">{row.name}</span>
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
                  </summary>
                  <SignalEvidence row={row} />
                </details>
              </td>
            </tr>
          </tbody>
        ))}
      </table>
    </div>
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

function SignalEvidence({ row }: { row: SignalRow }) {
  return (
    <div className="border-t border-border-muted bg-surface-secondary/50 px-3 py-4 sm:px-4">
      <p className="text-xs text-text-tertiary">
        {row.supportingVotes} of {SIGNAL_MAX_SCORE} checks currently support a bullish reading.
        Expandable evidence is the engine&apos;s own vote list — not an AI recommendation.
      </p>
      <ul className="mt-3 space-y-2">
        {row.votes.map((vote) => (
          <li key={vote.id} className="flex gap-2 text-sm">
            <span
              className={cn(
                "w-8 shrink-0 font-mono text-xs font-semibold",
                vote.passed ? "text-positive" : "text-negative",
              )}
            >
              <span className="sr-only">{vote.passed ? "Passed" : "Did not pass"}: </span>
              {vote.passed ? "Yes" : "No"}
            </span>
            <span>
              <span className="font-medium">{vote.label}</span>
              <span className="mt-0.5 block text-xs leading-5 text-text-secondary">
                {vote.detail}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-3 text-xs">
        <Link href={`/stocks/${row.ticker}`} className="hover:underline">
          Open {row.ticker} workspace
        </Link>
        <Link
          href={`/backtest?ticker=${row.ticker}`}
          className="text-text-tertiary hover:underline"
        >
          Backtest {row.ticker}
        </Link>
        <Link
          href={`/compare?tickers=${row.ticker}`}
          className="text-text-tertiary hover:underline"
        >
          Compare {row.ticker}
        </Link>
        <Link href={`/trade?ticker=${row.ticker}`} className="text-text-tertiary hover:underline">
          Trade {row.ticker}
        </Link>
      </div>
    </div>
  );
}
