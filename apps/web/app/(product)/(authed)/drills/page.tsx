/**
 * /drills — drill decks (A4.7, M9.3). Protected. Each deck lists its drills
 * with their status (not started, in progress, revealed) and process score;
 * an anonymised drill shows only its label until it is revealed. No ranking,
 * no leaderboard, no prizes.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { DeleteDeckButton } from "@/components/drills/delete-deck";
import { PageFrame } from "@/components/page-frame";
import {
  ResearchEmptyState,
  ResearchPageHeader,
  ResearchSubnav,
} from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
import { listDrillDecks } from "@/lib/api/drills";
import {
  DRILL_STATUS_LABEL,
  type DrillDeck,
  deckScoreLine,
  scoreLabel,
  universeLabel,
} from "@/lib/drills";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Drills" };

export default async function DrillsPage({
  searchParams,
}: {
  searchParams: Promise<{ deck?: string }>;
}) {
  const { deck: rawDeck } = await searchParams;
  const opened = Number(rawDeck);
  const decks = await listDrillDecks();

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <ResearchPageHeader
        path="/drills"
        title="Drills"
        description="Replays seeded from a setup's real historical triggers. Plan, trade, reveal: the score is whether you followed your plan, not the profit."
        actions={
          <Button asChild size="sm">
            <Link href="/drills/new" data-testid="drill-new">
              New deck
            </Link>
          </Button>
        }
      />
      <ResearchSubnav current="/drills" />
      <div className="mt-6 space-y-6" data-testid="drill-decks">
        {decks.length === 0 ? (
          <ResearchEmptyState
            title="No drill decks yet."
            action={
              <Button asChild size="sm">
                <Link href="/drills/new">Create a deck</Link>
              </Button>
            }
          >
            Start from a rule: "Drill this setup" on the screener, a setup, a strategy backtest or
            an event study opens the launch form with it filled in.
          </ResearchEmptyState>
        ) : (
          decks.map((deck) => <DeckCard key={deck.id} deck={deck} highlight={deck.id === opened} />)
        )}
      </div>
    </PageFrame>
  );
}

function DeckCard({ deck, highlight }: { deck: DrillDeck; highlight: boolean }) {
  const s = deck.summary;
  return (
    <section
      aria-labelledby={`deck-${deck.id}`}
      className={cn(
        "border-y border-border-muted py-4 sm:border-x sm:px-5",
        highlight && "border-brand/60",
      )}
      data-testid="drill-deck"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`deck-${deck.id}`} className="text-base font-semibold break-words">
            {deck.name}
          </h2>
          <p className="mt-1 font-mono text-xs break-words text-text-secondary">
            {deck.rule.canonical}
          </p>
          <p className="mt-1 text-xs text-text-tertiary">
            {universeLabel(deck.universe)} · {formatCloseDate(deck.from)} to{" "}
            {formatCloseDate(deck.to)} · {deck.k} of {deck.triggers_eligible} eligible triggers (
            {deck.triggers_found} found
            {deck.lag_skipped ? `, ${deck.lag_skipped} inside the 30-day lag` : ""}) · N{" "}
            {deck.lead_bars}, M {deck.follow_bars} · seed {deck.seed} ·{" "}
            {deck.anonymised ? "anonymised" : "not anonymised"}
          </p>
        </div>
        <DeleteDeckButton deckId={deck.id} drills={s.drills} />
      </div>
      <p className="mt-3 text-sm" data-testid="deck-score">
        <span className="font-medium">Process score:</span> {deckScoreLine(s)}
        <span className="text-text-tertiary">
          {" "}
          · {s.not_started} not started, {s.in_progress} in progress, {s.revealed} revealed
        </span>
      </p>
      <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {deck.drills.map((d) => (
          <li key={d.id}>
            <Link
              href={`/drills/${d.id}`}
              className="flex items-center justify-between gap-3 rounded-md border border-border-muted px-3 py-2 text-sm hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="drill-row"
              data-status={d.status}
            >
              <span className="min-w-0">
                <span className="font-semibold ticker">{d.label}</span>
                {d.trigger_date ? (
                  <span className="ml-2 text-xs text-text-tertiary">
                    {formatCloseDate(d.trigger_date)}
                  </span>
                ) : null}
              </span>
              <span className="shrink-0 text-right text-xs text-text-secondary">
                {DRILL_STATUS_LABEL[d.status]}
                {d.score ? <span className="block">{scoreLabel(d.score)}</span> : null}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
