"use client";

/**
 * NewsTimeline: headlines per day over the whole archive, stacked by tone
 * (news redesign, 26 Nov 2026). Drag across it to pick a date range; the page
 * reloads with `from`/`to`. The date fields in the filter form do the same
 * from the keyboard, so the brush is a pointer convenience only.
 *
 * Tone colours are the sentiment badge's: positive green, negative red, mixed
 * the warning tone, neutral and unscored grey. A headline's tone is Aegis's
 * label, not a price move.
 */

import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import type { NewsDay } from "@/lib/api/news";
import { type NewsQuery, dayIndex, newsHref } from "@/lib/news-view";
import { formatCloseDate } from "@/lib/stock-workspace";

const W = 1000;
const H = 72;

const LAYERS: { key: keyof Omit<NewsDay, "date">; fill: string; label: string }[] = [
  { key: "negative", fill: "var(--negative)", label: "negative" },
  { key: "mixed", fill: "var(--warning)", label: "mixed" },
  { key: "neutral", fill: "var(--text-tertiary)", label: "neutral" },
  {
    key: "unscored",
    fill: "color-mix(in oklab, var(--text-tertiary) 55%, transparent)",
    label: "unscored",
  },
  { key: "positive", fill: "var(--positive)", label: "positive" },
];

function total(day: NewsDay): number {
  return day.positive + day.neutral + day.negative + day.mixed + day.unscored;
}

export function NewsTimeline({ days, query }: { days: NewsDay[]; query: NewsQuery }) {
  const router = useRouter();
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ a: number; b: number } | null>(null);
  const max = useMemo(() => Math.max(1, ...days.map(total)), [days]);
  const step = W / Math.max(days.length, 1);
  const selected = drag
    ? { lo: Math.min(drag.a, drag.b), hi: Math.max(drag.a, drag.b) }
    : query.from || query.to
      ? {
          lo: dayIndex(days, query.from) ?? 0,
          hi: query.to ? (dayIndex(days, query.to) ?? days.length - 1) : days.length - 1,
        }
      : null;

  if (days.length === 0) return null;
  const sum = days.reduce((n, d) => n + total(d), 0);

  const indexAt = (clientX: number): number => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return 0;
    const x = ((clientX - rect.left) / rect.width) * W;
    return Math.min(days.length - 1, Math.max(0, Math.floor(x / step)));
  };

  return (
    <figure className="min-w-0" data-testid="news-timeline">
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-xs text-text-tertiary">
        <span>
          <span className="font-medium text-text-secondary">Headlines per Day</span> · drag to pick
          dates
        </span>
        <span className="font-mono">
          {sum.toLocaleString("en-US")} from {formatCloseDate(days[0].date)} to{" "}
          {formatCloseDate(days[days.length - 1].date)}
        </span>
      </figcaption>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Headlines per day by tone, ${days.length} days, busiest day ${max} headlines. Use the From and To fields to pick dates with the keyboard.`}
        className="block h-20 w-full cursor-crosshair touch-none select-none rounded-md border border-border-muted bg-card"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          const i = indexAt(event.clientX);
          setDrag({ a: i, b: i });
        }}
        onPointerMove={(event) => {
          if (drag) setDrag({ ...drag, b: indexAt(event.clientX) });
        }}
        onPointerUp={() => {
          if (!drag) return;
          const lo = Math.min(drag.a, drag.b);
          const hi = Math.max(drag.a, drag.b);
          setDrag(null);
          router.push(newsHref(query, { from: days[lo].date, to: days[hi].date }), {
            scroll: false,
          });
        }}
        onPointerCancel={() => setDrag(null)}
      >
        {selected ? (
          <rect
            x={selected.lo * step}
            width={(selected.hi - selected.lo + 1) * step}
            y={0}
            height={H}
            fill="color-mix(in oklab, var(--brand) 14%, transparent)"
          />
        ) : null}
        {days.map((day, i) => {
          let y = H;
          const dim = selected && (i < selected.lo || i > selected.hi);
          return (
            <g key={day.date} opacity={dim ? 0.35 : 1}>
              {LAYERS.map((layer) => {
                const value = day[layer.key] as number;
                if (!value) return null;
                const h = (value / max) * (H - 4);
                y -= h;
                return (
                  <rect
                    key={layer.key}
                    x={i * step + step * 0.12}
                    width={Math.max(step * 0.76, 0.6)}
                    y={y}
                    height={h}
                    fill={layer.fill}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-text-tertiary" aria-hidden>
        {[...LAYERS].reverse().map((layer) => (
          <li key={layer.key} className="flex items-center gap-1.5">
            <span className="size-2 rounded-sm" style={{ background: layer.fill }} />
            {layer.label[0].toUpperCase() + layer.label.slice(1)}
          </li>
        ))}
      </ul>
    </figure>
  );
}
