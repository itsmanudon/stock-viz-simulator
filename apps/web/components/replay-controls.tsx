"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import {
  type ReplayActionState,
  advanceReplayAction,
  cancelReplayAction,
} from "@/app/(product)/(authed)/replay/actions";
import { Button } from "@/components/ui/button";
import { formatReplayDay } from "@/lib/replay";

export function ReplayAdvanceControls({
  sessionId,
  currentAt,
  hasNext,
  readOnly,
  target = "replay",
}: {
  sessionId: number;
  currentAt: string;
  hasNext: boolean;
  readOnly: boolean;
  /** A4.7: a drill steps through `/v1/drills/{id}/advance` and is ended by its reveal. */
  target?: "replay" | "drill";
}) {
  const drill = target === "drill";
  const [advanceState, advance, advancing] = useActionState<ReplayActionState, FormData>(
    advanceReplayAction,
    {},
  );
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelState, cancel, cancelling] = useActionState<ReplayActionState, FormData>(
    cancelReplayAction,
    {},
  );

  if (readOnly && drill) return null;
  if (readOnly) {
    return (
      <div className="flex flex-wrap items-center gap-3 border-y border-border-muted py-4 sm:border-x sm:px-6">
        <Button asChild>
          <Link href="/replay">Start another replay</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3 border-y border-border-muted py-4 sm:border-x sm:px-6">
      <form action={advance}>
        <input type="hidden" name="session_id" value={sessionId} />
        <input type="hidden" name="current_at" value={currentAt} />
        <input type="hidden" name="target" value={target} />
        <Button
          type="submit"
          disabled={advancing}
          aria-label={
            hasNext ? "Advance to next session" : drill ? "Finish drill" : "Finish replay"
          }
        >
          {advancing
            ? "Advancing…"
            : hasNext
              ? "Next session"
              : drill
                ? "Finish drill"
                : "Finish replay"}
        </Button>
        <p className="mt-2 text-xs leading-5 text-text-tertiary">
          {hasNext
            ? "Moves to the next stored daily bar."
            : drill
              ? "This is the last bar. You can still trade it; finishing ends the drill."
              : "This is the last bar. You can still trade it; finishing ends the replay."}
        </p>
      </form>
      {advanceState.from && advanceState.to ? (
        <output className="block text-sm">
          Advanced: {formatReplayDay(advanceState.from)} → {formatReplayDay(advanceState.to)}
        </output>
      ) : null}
      {advanceState.error ? (
        <p role="alert" className="text-sm text-negative">
          {advanceState.error}
        </p>
      ) : null}

      {drill ? null : confirmCancel ? (
        <form action={cancel} className="flex flex-wrap items-center gap-2">
          <input type="hidden" name="session_id" value={sessionId} />
          <p className="text-sm text-text-secondary">Cancel this replay? It becomes read-only.</p>
          <Button type="submit" variant="destructive" size="sm" disabled={cancelling}>
            {cancelling ? "Cancelling…" : "Confirm cancel"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmCancel(false)}>
            Keep session
          </Button>
        </form>
      ) : (
        <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmCancel(true)}>
          Cancel replay
        </Button>
      )}
      {cancelState.error ? (
        <p role="alert" className="text-sm text-negative">
          {cancelState.error}
        </p>
      ) : null}
    </div>
  );
}
