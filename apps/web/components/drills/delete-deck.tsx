"use client";

import { useActionState, useState } from "react";

import { type DrillActionState, deleteDeckAction } from "@/app/(product)/(authed)/drills/actions";
import { Button } from "@/components/ui/button";

/** Two-step: "Delete deck…" then "Delete N drills" (or Keep). */
export function DeleteDeckButton({ deckId, drills }: { deckId: number; drills: number }) {
  const [confirm, setConfirm] = useState(false);
  const [state, action, pending] = useActionState<DrillActionState, FormData>(deleteDeckAction, {});
  if (!confirm) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setConfirm(true)}
        data-testid="deck-delete"
      >
        Delete deck…
      </Button>
    );
  }
  return (
    <form
      action={action}
      className="flex flex-wrap items-center gap-2"
      data-testid="deck-delete-confirm"
    >
      <input type="hidden" name="deck_id" value={deckId} />
      <p className="text-sm text-text-secondary">
        Delete this deck, its {drills} drill{drills === 1 ? "" : "s"}, their plans and replays?
      </p>
      <Button type="submit" variant="destructive" size="sm" disabled={pending} autoFocus>
        {pending ? "Deleting…" : "Delete"}
      </Button>
      <Button type="button" variant="ghost" size="sm" onClick={() => setConfirm(false)}>
        Keep deck
      </Button>
      {state.error ? (
        <span role="alert" className="text-sm text-negative">
          {state.error}
        </span>
      ) : null}
    </form>
  );
}
