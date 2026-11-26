"use client";

/**
 * A watchlist row's note and tags, edited in place (A2.5, M4.6).
 *
 * `NoteEditor` shows the note (or "Add note"); Edit opens a textarea with
 * Save and Cancel; Escape cancels and Ctrl/Cmd+Enter saves. `TagEditor`
 * shows the tags as chips, each removable, and an input that adds one or
 * more ("earnings, f&o").
 */

import { Pencil, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { saveItemAction } from "@/app/(product)/(authed)/watchlist/actions";
import { cn } from "@/lib/utils";
import { parseTagInput } from "@/lib/watchlist-columns";

export const NOTE_MAX = 2000;

export function NoteEditor({
  listId,
  ticker,
  note,
}: {
  listId: number;
  ticker: string;
  note: string | null | undefined;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note ?? "");
  const [shown, setShown] = useState(note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function save() {
    startTransition(async () => {
      const result = await saveItemAction(listId, ticker, { note: draft.trim() || null });
      if (result.error) {
        setError(result.error);
        return;
      }
      setShown(draft.trim());
      setError(null);
      setEditing(false);
      router.refresh();
    });
  }

  if (!editing) {
    return (
      <div className="flex min-w-0 items-start gap-1.5">
        {shown ? (
          <p
            className="min-w-0 text-xs whitespace-pre-line text-text-secondary"
            data-testid="watchlist-note"
          >
            {shown}
          </p>
        ) : null}
        <button
          type="button"
          onClick={() => {
            setDraft(shown);
            setEditing(true);
          }}
          className="inline-flex shrink-0 items-center gap-1 rounded-sm text-2xs text-text-tertiary hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={shown ? `Edit note for ${ticker}` : `Add a note for ${ticker}`}
        >
          <Pencil className="size-3" aria-hidden />
          {shown ? null : "Add note"}
        </button>
      </div>
    );
  }

  return (
    <div className="grid gap-1.5">
      <textarea
        // biome-ignore lint/a11y/noAutofocus: opened on request, the user expects the cursor here
        autoFocus
        value={draft}
        maxLength={NOTE_MAX}
        rows={3}
        aria-label={`Note for ${ticker}`}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            setEditing(false);
            setError(null);
          } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            save();
          }
        }}
        className="w-full min-w-[12rem] rounded-sm border border-input bg-transparent px-2 py-1.5 text-xs"
      />
      <div className="flex items-center gap-2 text-2xs">
        <button
          type="button"
          onClick={save}
          disabled={pending}
          className="rounded-sm border border-border-muted px-2 py-1 text-foreground hover:bg-surface-hover disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save note"}
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setError(null);
          }}
          className="px-1 text-text-tertiary hover:text-foreground"
        >
          Cancel
        </button>
        <span className="ml-auto font-mono text-text-tertiary">
          {draft.length}/{NOTE_MAX}
        </span>
      </div>
      {error ? (
        <p className="text-2xs text-negative" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function TagEditor({
  listId,
  ticker,
  tags,
}: {
  listId: number;
  ticker: string;
  tags: string[];
}) {
  const router = useRouter();
  const [current, setCurrent] = useState(tags);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function commit(next: string[]) {
    startTransition(async () => {
      const result = await saveItemAction(listId, ticker, { tags: next });
      if (result.error) {
        setError(result.error);
        return;
      }
      setCurrent(next);
      setDraft("");
      setError(null);
      router.refresh();
    });
  }

  return (
    <div className="grid gap-1">
      <ul className="flex flex-wrap items-center gap-1" aria-label={`Tags on ${ticker}`}>
        {current.map((tag) => (
          <li key={tag}>
            <span className="inline-flex items-center gap-1 rounded-full border border-border-muted bg-surface-secondary py-0.5 pr-1 pl-2 text-2xs">
              {tag}
              <button
                type="button"
                disabled={pending}
                onClick={() => commit(current.filter((t) => t !== tag))}
                className="rounded-full p-0.5 text-text-tertiary hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`Remove tag ${tag} from ${ticker}`}
              >
                <X className="size-3" aria-hidden />
              </button>
            </span>
          </li>
        ))}
        <li>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const added = parseTagInput(draft);
              if (!added.length) return;
              const lower = new Set(current.map((t) => t.toLocaleLowerCase()));
              commit([...current, ...added.filter((t) => !lower.has(t.toLocaleLowerCase()))]);
            }}
          >
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={current.length ? "+ tag" : "Add tags"}
              aria-label={`Add tags to ${ticker}`}
              maxLength={120}
              className={cn(
                "h-6 w-24 rounded-full border border-dashed border-border-muted bg-transparent px-2 text-2xs placeholder:text-text-tertiary",
                pending && "opacity-50",
              )}
            />
          </form>
        </li>
      </ul>
      {error ? (
        <p className="text-2xs text-negative" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
