"use client";

/**
 * The entry's review (A5.5): notes, mistakes, lessons, setup and mistake
 * tags. Always editable; the plan stays as it was locked. Ctrl/Cmd+Enter
 * saves from any field.
 */

import { useActionState, useId, useRef } from "react";

import {
  type EntryReviewState,
  saveEntryReviewAction,
} from "@/app/(product)/(authed)/portfolio/journal-actions";
import { useOutcomeSound } from "@/components/sound/sound-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { JournalEntry } from "@/lib/journal-entries";

const AREA =
  "min-h-20 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-text-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function JournalReviewForm({ entry }: { entry: JournalEntry }) {
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const [state, action, pending] = useActionState<EntryReviewState, FormData>(
    saveEntryReviewAction,
    {},
  );
  useOutcomeSound(state.ok, state.error, "success");

  return (
    <form
      ref={formRef}
      action={action}
      className="space-y-4"
      data-testid="journal-review-form"
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          formRef.current?.requestSubmit();
        }
      }}
    >
      <input type="hidden" name="entry_id" value={entry.id} />
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-notes`}>Review Notes</Label>
        <textarea
          id={`${id}-notes`}
          name="review_notes"
          defaultValue={entry.review_notes ?? ""}
          maxLength={4000}
          className={AREA}
          placeholder="What happened, and why you acted as you did."
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-mistakes`}>Mistakes</Label>
          <textarea
            id={`${id}-mistakes`}
            name="mistakes"
            defaultValue={entry.mistakes ?? ""}
            maxLength={4000}
            className={AREA}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-lessons`}>Lessons</Label>
          <textarea
            id={`${id}-lessons`}
            name="lessons"
            defaultValue={entry.lessons ?? ""}
            maxLength={4000}
            className={AREA}
          />
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-setup-tags`}>Setup Tags</Label>
          <Input
            id={`${id}-setup-tags`}
            name="setup_tags"
            defaultValue={entry.setup_tags.join(", ")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-mistake-tags`}>Mistake Tags</Label>
          <Input
            id={`${id}-mistake-tags`}
            name="mistake_tags"
            defaultValue={entry.mistake_tags.join(", ")}
          />
        </div>
      </div>
      <p className="text-xs text-text-tertiary">Tags are separated by commas, up to 12 of each.</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending} data-testid="journal-review-save">
          {pending ? "Saving…" : "Save Review"}
        </Button>
        <output aria-live="polite" className="text-sm">
          {state.error ? (
            <span className="text-loss">{state.error}</span>
          ) : state.ok ? (
            <span className="text-text-secondary">{state.ok}</span>
          ) : null}
        </output>
      </div>
    </form>
  );
}
