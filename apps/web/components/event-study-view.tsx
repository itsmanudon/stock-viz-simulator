/**
 * An event study's results (Phase 7.4): the windows table, the mean CAR path
 * as a small inline chart, and the events behind it. Server component; the
 * chart is plain SVG coloured from tokens.
 */

import Link from "next/link";

import type { EventStudy } from "@/lib/api/research";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

function pct(v: number | null): string {
  if (v === null) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`;
}

function windowLabel(start: number, end: number): string {
  const day = (n: number) => (n === 0 ? "day 0" : n > 0 ? `+${n}` : `${n}`);
  return start === end ? day(start) : `${day(start)} to ${day(end)}`;
}

export function CarPath({ study }: { study: EventStudy }) {
  const points = study.path.filter((p) => p.mean_car_pct !== null);
  if (points.length < 2) return null;
  const values = points.map((p) => p.mean_car_pct as number);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;
  const w = 320;
  const h = 120;
  const x = (i: number) => (i / (points.length - 1)) * w;
  const y = (v: number) => h - ((v - lo) / span) * h;
  const zeroIndex = points.findIndex((p) => p.offset === 0);
  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  return (
    <figure className="w-full max-w-md">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="h-32 w-full overflow-visible"
        role="img"
        aria-label={`Mean cumulative abnormal return from day ${points[0].offset} to day ${points.at(-1)?.offset}`}
      >
        <line x1={0} x2={w} y1={y(0)} y2={y(0)} className="stroke-border" strokeDasharray="3 3" />
        {zeroIndex >= 0 ? (
          <line
            x1={x(zeroIndex)}
            x2={x(zeroIndex)}
            y1={0}
            y2={h}
            className="stroke-text-tertiary"
            strokeDasharray="2 4"
          />
        ) : null}
        <path d={line.join(" ")} fill="none" className="stroke-brand" strokeWidth={2} />
      </svg>
      <figcaption className="mt-1 text-2xs text-text-tertiary">
        Mean CAR by session; the dotted line is the event day, the dashed one zero.
      </figcaption>
    </figure>
  );
}

export function EventStudyView({
  study,
  compact = false,
}: { study: EventStudy; compact?: boolean }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-text-tertiary">
        {study.events_used} of {study.events_found} news items used
        {study.events_incomplete ? `; ${study.events_incomplete} lacked a full window` : ""}
        {study.overlapping ? `; ${study.overlapping} overlap another on the same stock` : ""}.
        Benchmark {[...new Set(Object.values(study.benchmarks))].join(" and ") || "none"};{" "}
        {study.model}.
      </p>
      {study.enough ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Cumulative abnormal returns by window</caption>
          <thead>
            <tr className="text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
              <th scope="col" className="py-1.5">
                Window
              </th>
              <th scope="col" className="py-1.5 text-right">
                Mean CAR
              </th>
              <th scope="col" className="py-1.5 text-right">
                Std. error
              </th>
              <th scope="col" className="py-1.5 text-right">
                t
              </th>
            </tr>
          </thead>
          <tbody>
            {study.windows.map((w) => (
              <tr key={`${w.start}:${w.end}`} className="border-t border-border-muted">
                <td className="py-1.5">{windowLabel(w.start, w.end)}</td>
                <td
                  className={cn(
                    "py-1.5 text-right font-mono",
                    (w.mean_car_pct ?? 0) > 0 && "text-positive",
                    (w.mean_car_pct ?? 0) < 0 && "text-negative",
                  )}
                  data-financial
                >
                  {pct(w.mean_car_pct)}
                </td>
                <td className="py-1.5 text-right font-mono text-text-secondary">
                  {w.std_error_pct === null ? "—" : `${w.std_error_pct.toFixed(2)}%`}
                </td>
                <td className="py-1.5 text-right font-mono text-text-secondary">
                  {w.t_stat === null ? "—" : w.t_stat.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-text-secondary" data-testid="too-few-events">
          Fewer than {study.min_events} complete events: no averages are shown.
        </p>
      )}
      {study.enough && !compact ? <CarPath study={study} /> : null}
      {!compact && study.events.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs text-text-secondary">
            The {study.events.length} events, newest first
          </summary>
          <ul className="mt-2 divide-y divide-border-muted">
            {study.events.map((e) => (
              <li key={`${e.ticker}:${e.document_id}`} className="flex justify-between gap-3 py-2">
                <span className="min-w-0">
                  <span className="ticker mr-2 font-semibold">{e.ticker}</span>
                  <span className="text-text-secondary">{e.title}</span>
                  <span className="block text-2xs text-text-tertiary">
                    Event day {formatCloseDate(e.event_date)}
                  </span>
                </span>
                <span className="shrink-0 font-mono" data-financial>
                  {pct(e.car_pct)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="text-2xs text-text-tertiary">
        An association between news and price moves, not a cause. Aegis coverage starts when its
        sync did.
      </p>
    </div>
  );
}

/** The stock page's "News reactions" block (Phase 7.4), under its news. */
export function NewsReactions({
  ticker,
  negative,
  positive,
}: {
  ticker: string;
  negative: EventStudy | null;
  positive: EventStudy | null;
}) {
  if (!negative && !positive) return null;
  return (
    <section aria-labelledby="news-reactions-heading" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="news-reactions-heading" className="text-sm font-semibold">
          News reactions
        </h3>
        <Link
          href={`/news-reactions?tickers=${encodeURIComponent(ticker)}`}
          className="text-xs hover:underline"
        >
          Open the full study
        </Link>
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        {[
          ["After negative news", negative],
          ["After positive news", positive],
        ].map(([label, study]) =>
          study ? (
            <div key={label as string}>
              <p className="mb-2 text-xs font-medium text-text-secondary">{label as string}</p>
              <EventStudyView study={study as EventStudy} compact />
            </div>
          ) : null,
        )}
      </div>
    </section>
  );
}
