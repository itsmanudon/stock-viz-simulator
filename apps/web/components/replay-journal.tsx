"use client";

import { useActionState, useId } from "react";

import {
  type ReplayActionState,
  saveReplayJournalAction,
} from "@/app/(product)/(authed)/replay/actions";
import { ResearchSectionHeader } from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ReplayJournal } from "@/lib/api/replay";
import { cn } from "@/lib/utils";

export function ReplayJournalForm({
  sessionId,
  journal,
  hasFills,
  completed,
}: {
  sessionId: number;
  journal: ReplayJournal;
  hasFills: boolean;
  completed: boolean;
}) {
  const fieldId = useId();
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    saveReplayJournalAction,
    {},
  );
  const locked = journal.locked || hasFills;

  return (
    <section aria-labelledby={`${fieldId}-title`} className="space-y-3">
      <ResearchSectionHeader
        id={`${fieldId}-title`}
        title="Decision journal"
        description={
          locked
            ? "Thesis, invalidation, expected bars, and confidence are frozen after the first fill. Reflection stays editable."
            : "Write the thesis before the first fill. Those fields lock once a trade exists so the record stays point-in-time."
        }
      />
      <form
        action={action}
        className="space-y-4 border-y border-border-muted py-4 sm:border-x sm:px-6"
      >
        <input type="hidden" name="session_id" value={sessionId} />
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-thesis`}>Thesis</Label>
            <textarea
              id={`${fieldId}-thesis`}
              name="thesis"
              defaultValue={journal.thesis ?? ""}
              readOnly={locked}
              rows={4}
              className={textareaClass(locked)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-invalidation`}>Invalidation</Label>
            <textarea
              id={`${fieldId}-invalidation`}
              name="invalidation"
              defaultValue={journal.invalidation ?? ""}
              readOnly={locked}
              rows={4}
              className={textareaClass(locked)}
            />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-bars`}>Expected holding (bars)</Label>
            <Input
              id={`${fieldId}-bars`}
              name="expected_holding_bars"
              type="number"
              min={1}
              defaultValue={journal.expected_holding_bars ?? ""}
              readOnly={locked}
            />
          </div>
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium">Confidence (1–5)</legend>
            {locked ? (
              <input type="hidden" name="confidence" value={journal.confidence ?? ""} />
            ) : null}
            <div className="flex flex-wrap gap-2">
              {[1, 2, 3, 4, 5].map((value) => (
                <label key={value} className="inline-flex items-center gap-1 text-sm">
                  <input
                    type="radio"
                    name={locked ? undefined : "confidence"}
                    value={value}
                    defaultChecked={journal.confidence === value}
                    disabled={locked}
                  />
                  {value}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        {completed || locked ? (
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-reflection`}>
              {completed ? "What changed? What would you do differently?" : "Notes"}
            </Label>
            <textarea
              id={`${fieldId}-reflection`}
              name="reflection"
              defaultValue={journal.reflection ?? ""}
              rows={4}
              className={textareaClass(false)}
            />
          </div>
        ) : null}
        {state.error ? (
          <p role="alert" className="text-sm text-negative">
            {state.error}
          </p>
        ) : null}
        {state.status === "saved" ? <p className="text-sm text-positive">Journal saved.</p> : null}
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : locked ? "Save reflection" : "Save journal"}
        </Button>
      </form>
    </section>
  );
}

function textareaClass(readOnly: boolean): string {
  return cn(
    "w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
    readOnly && "cursor-default opacity-80",
  );
}
