/**
 * /portfolio/journal/[id]/replay — A6.10 (M9.5): "Replay my trade". A
 * read-only playback of a paper or imported entry: the bars (stored minutes
 * where they cover it, else daily), the real fills, the plan's lines, MAE and
 * MFE as they grew, and the hesitation strip. No orders.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { TradeReplayPlayer } from "@/components/journal/trade-replay-player";
import { MetaChip, PageHeader } from "@/components/page-header";
import { formatUtcDateTime } from "@/lib/api-time";
import { type TradeReplay, getTradeReplay } from "@/lib/api/journal-entries";
import { AuthedApiError } from "@/lib/api/server";

export const metadata: Metadata = { title: "Replay my trade" };

function hesitationLines(replay: TradeReplay): string[] {
  const h = replay.hesitation;
  if (!h) return ["No plan with an entry level, so there is no hesitation strip."];
  const unit = replay.interval === "1m" ? "minute" : "session";
  const lines: string[] = [];
  if (h.entry_touched_at && h.wait_bars !== null) {
    lines.push(
      h.wait_bars === 0
        ? `Filled on the ${unit} the plan's entry level was first touched.`
        : `Filled ${h.wait_bars} ${unit}${h.wait_bars === 1 ? "" : "s"} after the plan's entry level was first touched (${formatUtcDateTime(h.entry_touched_at)}).`,
    );
  } else {
    lines.push("The plan's entry level was not touched before the fill.");
  }
  if (h.stop_breached_at) {
    lines.push(
      h.stop_honoured
        ? `The price went through the stop (${formatUtcDateTime(h.stop_breached_at)}) and the position was closed on that ${unit}: stop honoured.`
        : `The price went through the stop (${formatUtcDateTime(h.stop_breached_at)}) and the position stayed open past it: stop not honoured.`,
    );
  } else if (replay.planned_stop) {
    lines.push("The price did not reach the stop while the position was held.");
  }
  return lines;
}

export default async function TradeReplayPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: raw } = await params;
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) notFound();
  let replay: TradeReplay;
  try {
    replay = await getTradeReplay(id);
  } catch (error) {
    if (error instanceof AuthedApiError && (error.status === 404 || error.status === 409)) {
      notFound();
    }
    throw error;
  }
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Portfolio · Journal"
        title={`Replay My Trade: ${replay.ticker ?? "Unknown symbol"}`}
        description="Your real fills, played back bar by bar. Read only: nothing here places an order."
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <MetaChip>{replay.side === "short" ? "Short" : "Long"}</MetaChip>
            <MetaChip>{replay.bars_note}</MetaChip>
            <Link
              href={`/portfolio/journal/${replay.entry_id}`}
              className="text-xs font-medium text-brand hover:underline"
            >
              Back to the entry
            </Link>
          </span>
        }
      />
      <TradeReplayPlayer replay={replay} />
      <section aria-labelledby="hesitation-title" className="space-y-2">
        <h2 id="hesitation-title" className="text-base font-semibold tracking-tight">
          Hesitation
        </h2>
        <ul
          className="list-disc space-y-1 pl-5 text-sm text-text-secondary"
          data-testid="trade-replay-hesitation"
        >
          {hesitationLines(replay).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="text-xs text-text-tertiary">
          {replay.hesitation?.note ?? replay.bars_note}{" "}
          {replay.excursions.reason ?? replay.excursions.note}
        </p>
      </section>
    </div>
  );
}
