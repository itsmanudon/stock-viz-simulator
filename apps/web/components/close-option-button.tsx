"use client";

import { useActionState, useState } from "react";

import {
  type CloseOptionState,
  closeOptionFormAction,
} from "@/app/(product)/(authed)/trade/options-actions";

const INITIAL: CloseOptionState = { error: null, closed: false };

/**
 * Close an open option in two steps (audit LG-8): the first click states what
 * it closes for, the second sends it. The amount is the position's current
 * value; the fill uses the same model price at submit. A refused close shows
 * here instead of the app error page.
 */
export function CloseOptionButton({
  optionId,
  label,
  valueText,
  short = false,
}: {
  optionId: number;
  label: string;
  valueText: string;
  /** A written leg is bought back (it costs), not sold (Phase 9.2). */
  short?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [state, action, pending] = useActionState(closeOptionFormAction, INITIAL);
  const buttonClass =
    "rounded-md border border-border px-2.5 py-1 text-xs font-medium outline-none transition-colors hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring";

  if (!confirming) {
    return (
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={`Close ${label}`}
          className={`${buttonClass} text-muted-foreground hover:text-foreground`}
        >
          {short ? "Buy back" : "Close"}
        </button>
        {state.error ? (
          <p role="alert" className="max-w-48 text-right text-2xs text-negative">
            {state.error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <form
      action={(formData) => {
        setConfirming(false);
        action(formData);
      }}
      className="flex flex-col items-end gap-1"
    >
      <input type="hidden" name="option_id" value={optionId} />
      <p className="text-2xs text-muted-foreground">
        {short ? `Buy back for about ${valueText}?` : `Close for about ${valueText}?`}
      </p>
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className={`${buttonClass} text-muted-foreground`}
        >
          Keep
        </button>
        <button
          type="submit"
          disabled={pending}
          aria-label={`Confirm closing ${label}`}
          className={`${buttonClass} text-foreground`}
        >
          Confirm close
        </button>
      </div>
    </form>
  );
}
