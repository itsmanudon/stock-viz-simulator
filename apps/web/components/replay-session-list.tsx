"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import {
  type ReplayActionState,
  cancelReplayAction,
} from "@/app/(product)/(authed)/replay/actions";
import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ReplaySessionList } from "@/lib/api/replay";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatReplayShortDate, replayProgressPct, replayStatusLabel } from "@/lib/replay";

export function ReplaySessionTable({ sessions }: { sessions: ReplaySessionList[] }) {
  if (sessions.length === 0) {
    return (
      <ResearchEmptyState title="No replay sessions yet">
        Start a historical range above. Replay Lab keeps an isolated book so your live paper
        portfolio never moves.
      </ResearchEmptyState>
    );
  }

  return (
    <section aria-labelledby="replay-sessions-heading" className="space-y-3">
      <ResearchSectionHeader
        id="replay-sessions-heading"
        title="Recent sessions"
        description="Resume an active replay or review a completed one. Dates are historical replay dates, not today."
      />
      <div className="border-y border-border-muted sm:border-x">
        <Table aria-label="Replay sessions">
          <TableHeader>
            <TableRow>
              <TableHead>Symbol</TableHead>
              <TableHead>Range</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Cash</TableHead>
              <TableHead className="text-right">Progress</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.map((row) => {
              const progress = replayProgressPct(
                row.start_at,
                row.current_at,
                row.end_at,
                row.status,
              );
              const href = `/replay/${row.id}`;
              return (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">{row.ticker}</TableCell>
                  <TableCell className="text-xs text-text-secondary">
                    {formatReplayShortDate(row.start_at)} → {formatReplayShortDate(row.end_at)}
                    <div className="text-text-tertiary">
                      Now {formatReplayShortDate(row.current_at)}
                    </div>
                  </TableCell>
                  <TableCell>{replayStatusLabel(row.status)}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatCurrency(row.cash_balance)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{progress}%</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button asChild variant="outline" size="sm">
                        <Link href={href}>{row.status === "active" ? "Resume" : "View"}</Link>
                      </Button>
                      {row.status === "active" ? <ReplayCancelControl sessionId={row.id} /> : null}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function ReplayCancelControl({ sessionId }: { sessionId: number }) {
  const [confirming, setConfirming] = useState(false);
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    cancelReplayAction,
    {},
  );

  if (!confirming) {
    return (
      <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(true)}>
        Cancel
      </Button>
    );
  }

  return (
    <form action={action} className="flex items-center gap-1">
      <input type="hidden" name="session_id" value={sessionId} />
      <Button type="submit" variant="destructive" size="sm" disabled={pending}>
        {pending ? "Cancelling…" : "Confirm"}
      </Button>
      <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Keep
      </Button>
      {state.error ? (
        <span className="sr-only" role="alert">
          {state.error}
        </span>
      ) : null}
    </form>
  );
}
