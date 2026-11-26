/**
 * A4.7: the reveal. The real symbol, company and dates, what happened after
 * the trigger, and the process score with R achieved beside it (not the score).
 */

import Link from "next/link";

import type { DrillReveal, DrillScore } from "@/lib/drills";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

const CHECK_TONE = {
  passed: "text-positive",
  failed: "text-negative",
  not_applicable: "text-text-tertiary",
} as const;
const CHECK_WORD = { passed: "Passed", failed: "Not followed", not_applicable: "Not applicable" };

export function DrillRevealPanel({
  reveal,
  score,
  sessionId,
  currency,
}: {
  reveal: DrillReveal;
  score: DrillScore | null;
  sessionId: number;
  currency: string;
}) {
  return (
    <section
      aria-labelledby="drill-reveal-heading"
      className="mt-6 space-y-5 border-y border-border-muted py-5 sm:border-x sm:px-6"
      data-testid="drill-reveal-panel"
    >
      <div>
        <p className="text-2xs font-medium tracking-[0.12em] text-text-secondary uppercase">
          Revealed
        </p>
        <h2 id="drill-reveal-heading" className="mt-1 text-2xl font-semibold tracking-[-0.025em]">
          <Link
            href={`/stocks/${encodeURIComponent(reveal.ticker)}`}
            className="ticker hover:underline"
          >
            {reveal.ticker}
          </Link>
          {reveal.name ? (
            <span className="ml-2 text-base font-normal text-text-secondary">{reveal.name}</span>
          ) : null}
        </h2>
        <p className="mt-1 text-sm text-text-secondary">
          {reveal.sector ? `${reveal.sector} · ` : ""}Trigger {formatCloseDate(reveal.trigger_date)}
          {reveal.date_offset_weeks
            ? ` (shown as ${formatCloseDate(reveal.shown_trigger_date)}, ${Math.abs(reveal.date_offset_weeks)} weeks ${reveal.date_offset_weeks > 0 ? "earlier" : "later"})`
            : ""}{" "}
          · session {formatCloseDate(reveal.session_start)} to {formatCloseDate(reveal.session_end)}
        </p>
      </div>

      <div>
        <h3 className="text-sm font-semibold">What happened after the trigger</h3>
        <dl className="mt-2 grid grid-cols-3 gap-3 text-sm sm:max-w-lg" data-testid="drill-after">
          {reveal.after.map((a) => (
            <div key={a.bars}>
              <dt className="text-xs text-text-tertiary">{a.bars} bars later</dt>
              <dd className="font-mono tabular-nums">
                {a.return_pct === null || a.return_pct === undefined ? (
                  "—"
                ) : (
                  <span className={a.return_pct >= 0 ? "text-positive" : "text-negative"}>
                    {a.return_pct > 0 ? "▲ +" : a.return_pct < 0 ? "▼ " : ""}
                    {a.return_pct.toFixed(2)}%
                  </span>
                )}
              </dd>
              {a.date ? (
                <dd className="text-2xs text-text-tertiary">{formatCloseDate(a.date)}</dd>
              ) : null}
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-text-tertiary">
          From the trigger bar's close. {reveal.next_bars.length} stored bars follow the session
          {reveal.next_bars.length
            ? `, to ${formatCloseDate(reveal.next_bars[reveal.next_bars.length - 1].ts.slice(0, 10))} at ${formatCurrency(reveal.next_bars[reveal.next_bars.length - 1].close, currency)}`
            : ""}
          .
        </p>
      </div>

      <div>
        <h3 className="text-sm font-semibold">Process score</h3>
        {!score ? (
          <p className="mt-1 text-sm text-text-secondary">
            No plan was written, so there is nothing to score.
          </p>
        ) : (
          <>
            <p className="mt-1 text-sm" data-testid="drill-score">
              {score.traded
                ? `${score.passed} of ${score.applicable} checks passed${score.followed_plan ? ": you followed your plan." : "."}`
                : "No trade was taken: nothing to score."}
            </p>
            <ul className="mt-2 space-y-1.5 text-sm">
              {score.checks.map((c) => (
                <li key={c.key} data-testid="drill-check" data-status={c.status}>
                  <span className={cn("font-medium", CHECK_TONE[c.status])}>
                    {c.label}: {CHECK_WORD[c.status]}
                  </span>{" "}
                  <span className="text-text-secondary">{c.detail}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm text-text-secondary" data-testid="drill-r">
              R achieved:{" "}
              <span className="font-mono tabular-nums">
                {score.r_achieved === null || score.r_achieved === undefined
                  ? "—"
                  : `${score.r_achieved > 0 ? "+" : ""}${score.r_achieved.toFixed(2)}R`}
              </span>{" "}
              (P&amp;L {formatCurrency(score.total_pnl, currency)}). {score.r_note}
            </p>
          </>
        )}
      </div>
      <p className="text-sm">
        <Link
          href={`/replay/${sessionId}?view=forensics`}
          className="underline-offset-4 hover:underline"
        >
          Review the replay's forensics
        </Link>{" "}
        ·{" "}
        <Link href="/drills" className="underline-offset-4 hover:underline">
          Back to the decks
        </Link>
      </p>
    </section>
  );
}
