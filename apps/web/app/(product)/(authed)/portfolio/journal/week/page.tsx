/**
 * /portfolio/journal/week — A9.12 (M11.6): one week of closed journal entries
 * against the four weeks before, and what to look at (fixed rules, each naming
 * its entries). `?week_end=YYYY-MM-DD` (default today, UTC) and `?book=`.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { FigureStrip } from "@/components/figure-strip";
import { PageHeader } from "@/components/page-header";
import { type WeeklyReview, getWeeklyReview } from "@/lib/api/brief";
import { shiftWeek, weekHref } from "@/lib/brief";
import { formatCloseDate } from "@/lib/stock-workspace";

export const metadata: Metadata = { title: "Weekly Review" };

export default async function WeeklyReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ week_end?: string; book?: string }>;
}) {
  const raw = await searchParams;
  const weekEnd = /^\d{4}-\d{2}-\d{2}$/.test(raw.week_end ?? "") ? raw.week_end : undefined;
  const book = raw.book && /^(\d+|all)$/.test(raw.book) ? raw.book : undefined;
  let review: WeeklyReview | null = null;
  try {
    review = await getWeeklyReview({ book, weekEnd });
  } catch {
    review = null;
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Portfolio & Tax"
        title="Weekly Review"
        description="This week's closed entries against the four weeks before, and what to look at."
      />
      {!review ? (
        <p className="text-sm text-negative" data-testid="weekly-error">
          The review could not be loaded just now.
        </p>
      ) : (
        <div className="space-y-4" data-testid="weekly-review">
          <nav className="flex items-center gap-3 text-sm" aria-label="Weeks">
            <Link href={weekHref(shiftWeek(review.week_end, -7), book)} className="underline">
              Previous Week
            </Link>
            <span data-testid="weekly-range">
              {formatCloseDate(review.week_start)} – {formatCloseDate(review.week_end)}
            </span>
            <Link href={weekHref(shiftWeek(review.week_end, 7), book)} className="underline">
              Next Week
            </Link>
          </nav>
          <FigureStrip
            label="This week"
            figures={[
              { label: "Entries Closed", value: String(review.week.entries) },
              { label: "Wins / Losses", value: `${review.week.wins} / ${review.week.losses}` },
              {
                label: "Mean R",
                value: review.week.mean_r == null ? "—" : `${review.week.mean_r.toFixed(2)}R`,
                note:
                  review.baseline_mean_r == null
                    ? undefined
                    : `${review.baseline_mean_r.toFixed(2)}R over ${review.baseline_weeks} weeks`,
              },
              {
                label: "Plans Followed",
                value: review.week.plans_scored
                  ? `${review.week.plans_followed} of ${review.week.plans_scored}`
                  : "—",
              },
            ]}
          />
          {Object.keys(review.week.net_by_currency).length ? (
            <p className="text-sm" data-testid="weekly-net">
              Net P&L:{" "}
              {Object.entries(review.week.net_by_currency)
                .map(([c, v]) => `${v.toFixed(2)} ${c}`)
                .join(" · ")}
            </p>
          ) : null}
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold">To Look At</h2>
            {review.look_at.length ? (
              <ul className="space-y-2" data-testid="weekly-look-at">
                {review.look_at.map((i) => (
                  <li key={i.key} className="text-sm" data-key={i.key}>
                    {i.text}
                    {i.entry_ids.length ? (
                      <span className="ml-1 text-xs">
                        {i.entry_ids.map((id) => (
                          <Link
                            key={id}
                            href={`/portfolio/journal/${id}`}
                            className="ml-1 underline"
                          >
                            Entry {id}
                          </Link>
                        ))}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-text-secondary">Nothing from the rules this week.</p>
            )}
          </section>
          {review.notes.map((n) => (
            <p key={n} className="text-xs text-text-secondary">
              {n}
            </p>
          ))}
          <p className="text-2xs text-text-tertiary">{review.method}</p>
        </div>
      )}
    </div>
  );
}
