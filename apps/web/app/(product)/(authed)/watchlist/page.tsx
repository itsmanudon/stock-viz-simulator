/**
 * /watchlist — the user's lists of securities they are monitoring (A2.5, M4.6).
 *
 * `?list=<id>` opens a list (default: the default list) and `?tag=` narrows
 * its rows to one tag. Rows show the list's column set (or the default
 * columns), a sparkline, the note and tags (edited in place), and the four
 * row actions. News under the table is for the open list's symbols.
 * Server-rendered; the editors and list management are client islands.
 * Watchlist stays under Portfolio; this is not an order blotter.
 */

import Link from "next/link";

import { NewsList } from "@/components/news-list";
import {
  MonitoringSubnav,
  OperationalEmptyState,
  OperationalPageHeader,
} from "@/components/operational-page-header";
import { PageFrame } from "@/components/page-frame";
import { MetaChip } from "@/components/page-header";
import { Sparkline } from "@/components/sparkline";
import { ColumnSetEditor, ColumnSetPicker } from "@/components/watchlist-columns";
import { AddWatchlistForm, WatchlistRowActions } from "@/components/watchlist-controls";
import { ListDot, ListManager, ListTabs, listHref } from "@/components/watchlist-lists";
import { NoteEditor, TagEditor } from "@/components/watchlist-row-editors";
import { getNewsForTickers, listSymbols } from "@/lib/api";
import { parseApiTimestamp } from "@/lib/api-time";
import {
  type ColumnSet,
  type WatchlistItems,
  type WatchlistList,
  listColumnSets,
  listWatchlistItems,
  listWatchlists,
} from "@/lib/api/watchlist";
import { dayMovePct } from "@/lib/operational-trading";
import { formatSignedPercent } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";
import {
  COLUMN_META,
  type ColumnKey,
  columnSign,
  formatColumnValue,
  hasTag,
  listColourVar,
  tagsOf,
} from "@/lib/watchlist-columns";

function fmtDate(iso: string): string {
  return parseApiTimestamp(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** The close's own date (audit RS-13): symbols end on different days. */
function closeLabel(close: string | null, at: string | null | undefined): string {
  if (close === null) return "No stored close";
  return formatCloseDate(at) ?? "Date unknown";
}

function toneClass(sign: number | null): string | undefined {
  if (sign === null || sign === 0) return undefined;
  return sign > 0 ? "text-positive" : "text-negative";
}

type Params = { list?: string; tag?: string };

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<Params>;
}) {
  const params = await searchParams;
  let lists: WatchlistList[] | null = null;
  try {
    lists = await listWatchlists();
  } catch {
    lists = null;
  }

  if (!lists || lists.length === 0) {
    return (
      <PageFrame width="workstation" className="py-5 sm:py-7">
        <OperationalPageHeader title="Watchlist" description="Securities you are monitoring." />
        <MonitoringSubnav current="/watchlist" />
        <div className="mt-6" role="alert">
          <OperationalEmptyState title="Watchlists are unavailable right now">
            <p>The list service did not answer. Reload the page in a moment.</p>
          </OperationalEmptyState>
        </div>
      </PageFrame>
    );
  }

  const requested = Number(params.list);
  const active =
    lists.find((list) => list.id === requested) ??
    lists.find((list) => list.is_default) ??
    lists[0];

  const [itemsResult, sets, universe] = await Promise.all([
    listWatchlistItems(active.id).catch(() => null as WatchlistItems | null),
    listColumnSets().catch(() => [] as ColumnSet[]),
    listSymbols().catch(() => []),
  ]);
  const allItems = itemsResult?.items ?? [];
  const columns = (itemsResult?.columns ?? []) as ColumnKey[];
  const activeSet = sets.find((set) => set.id === itemsResult?.column_set_id) ?? null;
  const tags = tagsOf(allItems);
  const tag =
    params.tag && tags.some((t) => t.toLowerCase() === params.tag?.toLowerCase())
      ? params.tag
      : undefined;
  const items = tag ? allItems.filter((item) => hasTag(item, tag)) : allItems;

  const listed = new Set(allItems.map((item) => item.ticker));
  const addable = universe
    .filter((symbol) => !listed.has(symbol.ticker))
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map((symbol) => ({ ticker: symbol.ticker, name: symbol.name }));

  // Aegis news for the open list's symbols (M4.6). null when it failed.
  const news =
    allItems.length > 0
      ? await getNewsForTickers(
          allItems.map((item) => item.ticker),
          10,
        ).catch(() => null)
      : [];

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <OperationalPageHeader
        title="Watchlist"
        description="Securities you are monitoring, in as many lists as you like. Last close is the latest stored daily bar, not a live quote."
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {lists.length} list{lists.length === 1 ? "" : "s"} · {allItems.length} symbol
              {allItems.length === 1 ? "" : "s"} on {active.name}
            </span>
            <MetaChip>Stored daily closes, not live quotes</MetaChip>
          </span>
        }
      />
      <MonitoringSubnav current="/watchlist" />

      <div className="mt-5 grid gap-4">
        <ListTabs lists={lists} activeId={active.id} />
        <ListManager lists={lists} active={active} />
      </div>

      <div
        className="mt-5 rounded-md border border-border-muted border-l-4 bg-card px-4 py-4"
        style={{ borderLeftColor: listColourVar(active.colour) }}
      >
        <AddWatchlistForm symbols={addable} watchlistId={active.id} />
      </div>

      {itemsResult === null ? (
        <div className="mt-6" role="alert">
          <OperationalEmptyState title={`${active.name} could not be loaded`}>
            <p>The list's rows did not load. Reload the page in a moment.</p>
          </OperationalEmptyState>
        </div>
      ) : allItems.length === 0 ? (
        <div className="mt-6">
          <OperationalEmptyState
            title="Nothing on this list yet"
            action={
              <Link href="/screener" className="text-sm hover:underline">
                Find symbols in the Screener
              </Link>
            }
          >
            <p>
              Add a ticker above, use "Add to list…" on a stock page, or tick rows in the Screener
              and add them in bulk.
            </p>
          </OperationalEmptyState>
        </div>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              {tags.length ? (
                <>
                  <span className="text-text-secondary">Filter by tag</span>
                  <ul aria-label="Tags" className="flex flex-wrap gap-1.5">
                    <li>
                      <Link
                        href={listHref(active.id)}
                        aria-current={tag ? undefined : "true"}
                        className={cn(
                          "inline-flex min-h-7 items-center rounded-full border px-2.5",
                          tag
                            ? "border-border-muted text-text-secondary hover:bg-surface-hover"
                            : "border-brand/60 text-foreground",
                        )}
                      >
                        All
                      </Link>
                    </li>
                    {tags.map((t) => {
                      const on = tag?.toLowerCase() === t.toLowerCase();
                      return (
                        <li key={t}>
                          <Link
                            href={listHref(active.id, { tag: t })}
                            aria-current={on ? "true" : undefined}
                            className={cn(
                              "inline-flex min-h-7 items-center rounded-full border px-2.5",
                              on
                                ? "border-brand/60 text-foreground"
                                : "border-border-muted text-text-secondary hover:bg-surface-hover",
                            )}
                          >
                            {t}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </>
              ) : (
                <span className="text-text-tertiary">Tag rows to filter them.</span>
              )}
            </div>
            <ColumnSetPicker listId={active.id} sets={sets} activeSetId={activeSet?.id ?? null} />
          </div>

          <details className="mt-3 rounded-md border border-border-muted bg-card px-4 py-3">
            <summary className="cursor-pointer text-xs font-medium text-text-secondary">
              {activeSet ? `Edit columns: ${activeSet.name}` : "Customise columns"}
            </summary>
            <div className="mt-3">
              <ColumnSetEditor
                key={`${active.id}:${activeSet?.id ?? "default"}`}
                listId={active.id}
                set={activeSet}
                columns={columns}
              />
            </div>
          </details>

          {items.length === 0 ? (
            <p className="mt-5 text-sm text-text-secondary">
              No row on {active.name} has the tag {tag}.{" "}
              <Link href={listHref(active.id)} className="underline">
                Show all
              </Link>
            </p>
          ) : null}

          {/* Cards under md, where the table scrolled sideways (audit P1). */}
          <ul
            aria-label="Watched securities"
            className={cn("mt-5 grid gap-3 md:hidden", items.length === 0 && "hidden")}
          >
            {items.map((item) => {
              const closes = (item.closes ?? []).map(Number);
              const move = dayMovePct(closes[0], closes[closes.length - 1]);
              const currency = item.currency ?? "USD";
              return (
                <li
                  key={item.ticker}
                  className="grid gap-3 rounded-2xl border border-border-muted bg-card p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/stocks/${item.ticker}`}
                        className="ticker text-base font-medium hover:underline"
                      >
                        {item.ticker}
                      </Link>
                      <p className="truncate text-xs text-text-tertiary">{item.name}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-2xs text-text-tertiary">
                        {closeLabel(item.last_close, item.last_close_at)}
                      </p>
                      <p className={cn("font-mono text-xs", toneClass(move))} data-financial>
                        {move !== null && move !== 0 ? (
                          <span aria-hidden>{move > 0 ? "▲ " : "▼ "}</span>
                        ) : null}
                        {formatSignedPercent(move)} · 30 days
                      </p>
                    </div>
                  </div>
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                    {columns.map((key) => (
                      <div key={key} className="flex min-w-0 justify-between gap-2">
                        <dt className="text-text-tertiary">{COLUMN_META[key].label}</dt>
                        <dd
                          className={cn(
                            "truncate text-right",
                            COLUMN_META[key].kind !== "text" && "font-mono",
                            toneClass(columnSign(key, item.values)),
                          )}
                        >
                          {formatColumnValue(key, item.values, currency)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <Sparkline closes={closes} className="h-10 w-full" />
                  <NoteEditor listId={active.id} ticker={item.ticker} note={item.note} />
                  <TagEditor listId={active.id} ticker={item.ticker} tags={item.tags ?? []} />
                  <div className="flex items-center justify-between gap-3 border-t border-border-muted pt-3">
                    <span className="text-xs text-text-tertiary">
                      Added {fmtDate(item.added_at)}
                    </span>
                    <WatchlistRowActions ticker={item.ticker} watchlistId={active.id} />
                  </div>
                </li>
              );
            })}
          </ul>
          <div
            className={cn(
              "mt-5 hidden overflow-x-auto rounded-md border border-border-muted bg-card md:block",
              items.length === 0 && "md:hidden",
            )}
          >
            <table className="w-full min-w-[48rem] text-sm">
              <caption className="sr-only">Watched securities on {active.name}</caption>
              <thead>
                <tr className="border-b border-border-muted text-left text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                  <th scope="col" className="px-3 py-2.5">
                    Ticker
                  </th>
                  {columns.map((key) => (
                    <th
                      key={key}
                      scope="col"
                      title={COLUMN_META[key].hint}
                      className={cn(
                        "px-3 py-2.5",
                        COLUMN_META[key].kind !== "text" && "text-right",
                      )}
                    >
                      {titleCase(COLUMN_META[key].label)}
                    </th>
                  ))}
                  <th scope="col" className="hidden w-[7.5rem] px-3 py-2.5 lg:table-cell">
                    30-Day
                  </th>
                  <th scope="col" className="px-3 py-2.5">
                    Note and tags
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const closes = (item.closes ?? []).map(Number);
                  const currency = item.currency ?? "USD";
                  return (
                    <tr
                      key={item.ticker}
                      className="border-b border-border-muted align-top last:border-0"
                    >
                      <td className="px-3 py-3">
                        <Link
                          href={`/stocks/${item.ticker}`}
                          className="ticker font-semibold hover:underline"
                        >
                          {item.ticker}
                        </Link>
                        <span className="block max-w-[11rem] truncate text-2xs text-text-tertiary">
                          {item.name}
                        </span>
                        <span className="block text-2xs text-text-tertiary">
                          {closeLabel(item.last_close, item.last_close_at)}
                        </span>
                      </td>
                      {columns.map((key) => (
                        <td
                          key={key}
                          className={cn(
                            "px-3 py-3",
                            COLUMN_META[key].kind === "text"
                              ? "text-text-secondary"
                              : "text-right font-mono",
                            toneClass(columnSign(key, item.values)),
                          )}
                          data-financial={COLUMN_META[key].kind === "text" ? undefined : true}
                        >
                          {formatColumnValue(key, item.values, currency)}
                        </td>
                      ))}
                      <td className="hidden px-3 py-3 lg:table-cell">
                        <Sparkline closes={closes} />
                      </td>
                      <td className="max-w-[18rem] space-y-1.5 px-3 py-3">
                        <NoteEditor listId={active.id} ticker={item.ticker} note={item.note} />
                        <TagEditor listId={active.id} ticker={item.ticker} tags={item.tags ?? []} />
                      </td>
                      <td className="px-3 py-3 text-right">
                        <WatchlistRowActions ticker={item.ticker} watchlistId={active.id} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <section aria-labelledby="watchlist-news-heading" className="mt-8">
            <h2
              id="watchlist-news-heading"
              className="flex items-center gap-2 text-sm font-semibold"
            >
              <ListDot colour={active.colour} />
              News for {active.name}
            </h2>
            <p className="mt-1 text-xs text-text-tertiary">
              Headlines linked to the symbols on this list, newest first. Collected once a day.
            </p>
            <div className="mt-4">
              {news === null ? (
                <p className="text-sm text-muted-foreground">
                  News is unavailable right now. Try again shortly.
                </p>
              ) : (
                <NewsList articles={news} />
              )}
            </div>
          </section>
        </>
      )}
    </PageFrame>
  );
}
