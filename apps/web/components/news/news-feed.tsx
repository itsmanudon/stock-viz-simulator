"use client";

/**
 * NewsFeed: the archive page's headlines (news redesign, 26 Nov 2026).
 *
 * - Days: a sticky header per UTC day of `available_at` with the day's tone
 *   split (every headline, grouped ones too).
 * - Stories: the same event from several outlets is one row with
 *   "+N more sources" (`groupStories`: same day, same tickers, similar
 *   headline words; there is no article text to compare).
 * - Price reactions: each linked ticker's move on the session after the
 *   headline, with a small sparkline (five closes either side). Association,
 *   not cause; the chip's title says so.
 * - "New since your last visit": the newest `available_at` this browser saw on
 *   the first page is kept in localStorage (`stockviz:news-last-seen`, a
 *   convenience: every access guarded) and newer headlines are marked.
 * - Keys (outside a field): j / k move between headlines, o opens the
 *   original (/ is `NewsSearchShortcut`, mounted with the filters).
 *
 * Headline, source, dates and links only: Aegis stores no article text.
 */

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { SentimentBadge } from "@/components/sentiment-badge";
import type { NewsFeedItem, NewsReaction } from "@/lib/api/news";
import {
  type NewsDayGroup,
  type NewsSentiment,
  signedPct,
  sparkPath,
  sparkPoint,
} from "@/lib/news-view";
import { formatCloseDate } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";

const LAST_SEEN_KEY = "stockviz:news-last-seen";
const ROW_SELECTOR = "[data-news-row]";

function readLastSeen(): string | null {
  try {
    return window.localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(value: string): void {
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, value);
  } catch {
    // A blocked store only loses the marker.
  }
}

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT" ||
      target.isContentEditable)
  );
}

/** "14:05 UTC", read from the string so the zone never shifts it. */
function utcTime(iso: string): string {
  return `${iso.slice(11, 16)} UTC`;
}

function dayLabel(date: string): string {
  const d = new Date(`${date}T00:00:00Z`);
  const weekday = d.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  return `${weekday}, ${formatCloseDate(date)}`;
}

const TONE_FILL: Record<NewsSentiment, string> = {
  positive: "var(--positive)",
  negative: "var(--negative)",
  mixed: "var(--warning)",
  neutral: "var(--text-tertiary)",
  unscored: "color-mix(in oklab, var(--text-tertiary) 45%, transparent)",
};

function ToneBar({ tone }: { tone: Record<NewsSentiment, number> }) {
  const total = Object.values(tone).reduce((a, b) => a + b, 0);
  if (!total) return null;
  const order: NewsSentiment[] = ["positive", "neutral", "mixed", "unscored", "negative"];
  const words = order
    .filter((k) => tone[k])
    .map((k) => `${tone[k]} ${k}`)
    .join(", ");
  return (
    <span className="flex items-center gap-2">
      <span
        role="img"
        aria-label={`Tone: ${words}`}
        title={words}
        className="flex h-1.5 w-24 overflow-hidden rounded-full bg-surface-secondary sm:w-36"
      >
        {order.map((k) =>
          tone[k] ? (
            <span
              key={k}
              style={{ width: `${(tone[k] / total) * 100}%`, background: TONE_FILL[k] }}
            />
          ) : null,
        )}
      </span>
      <span className="font-mono text-2xs text-text-tertiary">{total}</span>
    </span>
  );
}

function ReactionChip({ reaction }: { reaction: NewsReaction }) {
  const change = reaction.change_pct;
  const up = change != null && change > 0;
  const down = change != null && change < 0;
  const w = 44;
  const h = 16;
  const point = sparkPoint(reaction.closes, reaction.reaction_index, w, h);
  const title = `${reaction.ticker} ${change == null ? "had no earlier close stored" : `closed ${signedPct(change)}`} on ${formatCloseDate(reaction.session_date)}, the first session after this headline. Association, not cause.`;
  return (
    <Link
      href={`/stocks/${encodeURIComponent(reaction.ticker)}`}
      title={title}
      aria-label={title}
      data-testid="news-reaction"
      className="inline-flex items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary/60 py-0.5 pr-2 pl-2.5 text-2xs transition-colors hover:border-border hover:bg-surface-hover"
    >
      <span className="ticker font-semibold">{reaction.ticker}</span>
      {/* biome-ignore lint/a11y/noSvgWithoutTitle: decorative; the chip's label states the move */}
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className="shrink-0">
        <path
          d={sparkPath(reaction.closes, w, h)}
          fill="none"
          stroke="var(--text-tertiary)"
          strokeWidth="1.25"
        />
        {point ? (
          <circle
            cx={point.x}
            cy={point.y}
            r="2"
            fill={up ? "var(--positive)" : down ? "var(--negative)" : "var(--foreground)"}
          />
        ) : null}
      </svg>
      <span
        className={cn(
          "font-mono tabular-nums",
          up ? "text-positive" : down ? "text-negative" : "text-text-tertiary",
        )}
      >
        {up ? "▲ " : down ? "▼ " : ""}
        {signedPct(change)}
      </span>
    </Link>
  );
}

function TickerChips({ item }: { item: NewsFeedItem }) {
  const reacted = new Set(item.reactions?.map((r) => r.ticker));
  const plain = item.tickers.filter((t) => !reacted.has(t));
  if (!item.reactions?.length && !plain.length) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {item.reactions?.map((r) => (
        <ReactionChip key={r.ticker} reaction={r} />
      ))}
      {plain.map((t) => (
        <Link
          key={t}
          href={`/stocks/${encodeURIComponent(t)}`}
          className="ticker rounded-full border border-border-muted px-2 py-0.5 text-2xs font-semibold hover:bg-surface-hover"
        >
          {t}
        </Link>
      ))}
    </div>
  );
}

function Headline({ item, isNew }: { item: NewsFeedItem; isNew: boolean }) {
  const title = item.url ? (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      data-news-link
      className="text-sm leading-snug font-medium text-foreground decoration-text-tertiary underline-offset-4 hover:underline sm:text-[0.95rem]"
    >
      {item.title}
      <span className="sr-only"> (opens the original in a new tab)</span>
    </a>
  ) : (
    <span data-news-link tabIndex={-1} className="text-sm leading-snug font-medium">
      {item.title}
    </span>
  );
  return (
    <div className="min-w-0">
      <div className="flex items-start gap-2">
        {isNew ? (
          <span
            className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand"
            role="img"
            aria-label="New since your last visit"
            data-testid="news-new-dot"
          />
        ) : null}
        <div className="min-w-0">{title}</div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-text-tertiary">
        <span className="text-text-secondary">{item.source}</span>
        <span aria-hidden>·</span>
        <time dateTime={item.available_at}>{utcTime(item.available_at)}</time>
        {item.topic ? (
          <span className="rounded-full border border-border-muted px-2 py-px text-2xs">
            {titleCase(item.topic.replaceAll("_", " "))}
          </span>
        ) : null}
        <SentimentBadge sentiment={item.sentiment ?? null} />
      </div>
      <TickerChips item={item} />
    </div>
  );
}

export function NewsFeed({
  days,
  isFirstPage,
}: {
  days: NewsDayGroup[];
  isFirstPage: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [lastSeen, setLastSeen] = useState<string | null>(null);
  const newest = days[0]?.stories[0]?.lead.available_at ?? null;

  // Read the marker once, then move it to this page's newest after a moment,
  // so a reload still shows what was new on arrival.
  useEffect(() => {
    if (!isFirstPage || !newest) return;
    const seen = readLastSeen();
    setLastSeen(seen);
    const timer = window.setTimeout(() => {
      if (!seen || newest > seen) writeLastSeen(newest);
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [isFirstPage, newest]);

  const newCount = useMemo(() => {
    if (!lastSeen) return 0;
    let n = 0;
    for (const day of days)
      for (const s of day.stories)
        for (const item of [s.lead, ...s.others]) if (item.available_at > lastSeen) n += 1;
    return n;
  }, [days, lastSeen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return;
      if (event.key !== "j" && event.key !== "k" && event.key !== "o") return;
      const rows = Array.from(rootRef.current?.querySelectorAll<HTMLElement>(ROW_SELECTOR) ?? []);
      if (!rows.length) return;
      const active = document.activeElement?.closest<HTMLElement>(ROW_SELECTOR) ?? null;
      const at = active ? rows.indexOf(active) : -1;
      if (event.key === "o") {
        if (at < 0) return;
        const link = rows[at].querySelector<HTMLAnchorElement>("a[data-news-link]");
        if (link) {
          event.preventDefault();
          link.click();
        }
        return;
      }
      event.preventDefault();
      const next = event.key === "j" ? Math.min(rows.length - 1, at + 1) : Math.max(0, at - 1);
      rows[next].focus();
      rows[next].scrollIntoView?.({ block: "nearest" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div ref={rootRef} data-testid="news-feed" className="min-w-0">
      {newCount > 0 && lastSeen ? (
        <p
          className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand/40 bg-brand/10 px-3 py-1 text-xs"
          data-testid="news-new-banner"
        >
          <span className="size-1.5 rounded-full bg-brand" aria-hidden />
          {newCount} new since your last visit ({formatCloseDate(lastSeen)})
        </p>
      ) : null}
      <p className="sr-only">
        Keys: j and k move between headlines, o opens the original, / searches.
      </p>
      {days.map((day) => (
        <section key={day.date} aria-label={dayLabel(day.date)} className="mb-2">
          <header className="sticky top-14 z-10 -mx-1 flex items-center justify-between gap-3 border-b border-border-muted bg-background/90 px-1 py-2 backdrop-blur-md">
            <h2 className="text-xs font-semibold tracking-[0.02em] text-text-secondary">
              {dayLabel(day.date)}
            </h2>
            <ToneBar tone={day.tone} />
          </header>
          <ol className="divide-y divide-border-muted">
            {day.stories.map((story) => (
              <li
                key={story.lead.id}
                tabIndex={-1}
                data-news-row
                data-sentiment={story.lead.sentiment ?? "unscored"}
                className="relative py-3.5 outline-none focus-visible:bg-surface-hover/60 focus-visible:ring-1 focus-visible:ring-ring"
              >
                <Headline
                  item={story.lead}
                  isNew={Boolean(lastSeen && story.lead.available_at > lastSeen)}
                />
                {story.others.length ? (
                  <details className="group mt-2" data-testid="news-story-more">
                    <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-full border border-border-muted px-2.5 py-0.5 text-2xs text-text-secondary hover:bg-surface-hover [&::-webkit-details-marker]:hidden">
                      +{story.others.length} more source{story.others.length === 1 ? "" : "s"}
                      <span className="transition-transform group-open:rotate-90" aria-hidden>
                        ›
                      </span>
                    </summary>
                    <ul className="mt-2 space-y-2 border-l border-border-muted pl-3">
                      {story.others.map((other) => (
                        <li key={other.id} className="text-xs">
                          {other.url ? (
                            <a
                              href={other.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-text-secondary hover:text-foreground hover:underline"
                            >
                              {other.title}
                            </a>
                          ) : (
                            <span className="text-text-secondary">{other.title}</span>
                          )}
                          <span className="ml-2 text-text-tertiary">
                            {other.source} · {utcTime(other.available_at)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
