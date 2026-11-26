"use client";

import { useActionState, useState } from "react";

import { type DrillActionState, revealDrillAction } from "@/app/(product)/(authed)/drills/actions";
import { Button } from "@/components/ui/button";

/** Reveal: one step once the drill is finished; two steps to end it early. */
export function DrillRevealButton({ drillId, finished }: { drillId: number; finished: boolean }) {
  const [confirm, setConfirm] = useState(false);
  const [state, action, pending] = useActionState<DrillActionState, FormData>(
    revealDrillAction,
    {},
  );
  if (!finished && !confirm) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setConfirm(true)}
        data-testid="drill-end-early"
      >
        End early and reveal…
      </Button>
    );
  }
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="drill_id" value={drillId} />
      {!finished ? (
        <p className="text-sm text-text-secondary">
          End the drill now? Open orders are cancelled and the plan is scored as it stands.
        </p>
      ) : null}
      <Button type="submit" disabled={pending} data-testid="drill-reveal" autoFocus={!finished}>
        {pending ? "Revealing…" : finished ? "Reveal the drill" : "End and reveal"}
      </Button>
      {!finished ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => setConfirm(false)}>
          Keep going
        </Button>
      ) : null}
      {state.error ? (
        <span role="alert" className="text-sm text-negative">
          {state.error}
        </span>
      ) : null}
    </form>
  );
}
