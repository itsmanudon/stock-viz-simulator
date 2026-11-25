"use client";

/**
 * Column sets for /watchlist (A2.5, M4.6).
 *
 * `ColumnSetPicker` chooses which saved set the open list shows ("Default
 * columns" = none); the choice is saved on the list. `ColumnSetEditor`
 * ticks columns from the API's allow-list and orders them with Up/Down
 * buttons (keyboard reachable, no drag), then saves over the chosen set,
 * saves a new one, or deletes it.
 */

import { ArrowDown, ArrowUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import {
  type ListActionState,
  chooseColumnSetAction,
  deleteColumnSetAction,
  saveColumnSetAction,
} from "@/app/(product)/(authed)/watchlist/actions";
import { Button } from "@/components/ui/button";
import type { ColumnSet } from "@/lib/api/watchlist";
import { COLUMN_KEYS, COLUMN_META, type ColumnKey } from "@/lib/watchlist-columns";

export function ColumnSetPicker({
  listId,
  sets,
  activeSetId,
}: {
  listId: number;
  sets: ColumnSet[];
  activeSetId: number | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <label className="flex items-center gap-2 text-xs">
      <span className="font-medium text-text-secondary">Columns</span>
      <select
        value={activeSetId ?? ""}
        disabled={pending}
        onChange={(event) => {
          const value = event.target.value;
          startTransition(async () => {
            const result = await chooseColumnSetAction(listId, value ? Number(value) : null);
            setError(result.error ?? null);
            router.refresh();
          });
        }}
        className="h-8 rounded-sm border border-input bg-transparent px-2 text-xs"
      >
        <option value="">Default columns</option>
        {sets.map((set) => (
          <option key={set.id} value={set.id}>
            {set.name}
          </option>
        ))}
      </select>
      {error ? (
        <span className="text-negative" role="alert">
          {error}
        </span>
      ) : null}
    </label>
  );
}

export function ColumnSetEditor({
  listId,
  set,
  columns,
}: {
  listId: number;
  /** The set being edited; null when the list shows the default columns. */
  set: ColumnSet | null;
  /** What the list shows now, the editor's starting point. */
  columns: ColumnKey[];
}) {
  const router = useRouter();
  const [chosen, setChosen] = useState<ColumnKey[]>(columns);
  const [state, action, pending] = useActionState<ListActionState, FormData>(
    saveColumnSetAction,
    {},
  );
  const [deleting, startDelete] = useTransition();
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function toggle(key: ColumnKey, on: boolean) {
    setChosen((now) => (on ? [...now, key] : now.filter((k) => k !== key)));
  }

  function move(key: ColumnKey, step: -1 | 1) {
    setChosen((now) => {
      const from = now.indexOf(key);
      const to = from + step;
      if (from < 0 || to < 0 || to >= now.length) return now;
      const next = [...now];
      [next[from], next[to]] = [next[to], next[from]];
      return next;
    });
  }

  const unchosen = COLUMN_KEYS.filter((key) => !chosen.includes(key));

  return (
    <form action={action} className="grid gap-4" aria-label="Column set">
      <input type="hidden" name="watchlist_id" value={listId} />
      {set ? <input type="hidden" name="column_set_id" value={set.id} /> : null}
      {chosen.map((key) => (
        <input key={key} type="hidden" name="columns" value={key} />
      ))}
      <label className="text-xs">
        <span className="mb-1 block font-medium text-text-secondary">Set name</span>
        <input
          name="name"
          required
          maxLength={64}
          defaultValue={set?.name ?? ""}
          placeholder="Momentum"
          className="flex h-9 w-full max-w-xs rounded-sm border border-input bg-transparent px-3 text-sm"
        />
      </label>
      <div className="grid gap-4 md:grid-cols-2">
        <section aria-labelledby="columns-shown">
          <h4 id="columns-shown" className="mb-2 text-xs font-medium text-text-secondary">
            Shown, in order ({chosen.length})
          </h4>
          {chosen.length === 0 ? (
            <p className="text-xs text-text-tertiary">Pick at least one column.</p>
          ) : (
            <ol className="grid gap-1" aria-label="Chosen columns">
              {chosen.map((key, index) => (
                <li
                  key={key}
                  className="flex items-center gap-2 rounded-sm border border-border-muted px-2 py-1 text-xs"
                >
                  <input
                    type="checkbox"
                    checked
                    onChange={(event) => toggle(key, event.target.checked)}
                    aria-label={`Show ${COLUMN_META[key].label}`}
                    className="size-3.5 accent-brand"
                  />
                  <span className="flex-1">{COLUMN_META[key].label}</span>
                  <button
                    type="button"
                    onClick={() => move(key, -1)}
                    disabled={index === 0}
                    aria-label={`Move ${COLUMN_META[key].label} up`}
                    className="rounded-sm p-1 text-text-tertiary hover:text-foreground disabled:opacity-30"
                  >
                    <ArrowUp className="size-3" aria-hidden />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(key, 1)}
                    disabled={index === chosen.length - 1}
                    aria-label={`Move ${COLUMN_META[key].label} down`}
                    className="rounded-sm p-1 text-text-tertiary hover:text-foreground disabled:opacity-30"
                  >
                    <ArrowDown className="size-3" aria-hidden />
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section aria-labelledby="columns-available">
          <h4 id="columns-available" className="mb-2 text-xs font-medium text-text-secondary">
            Available
          </h4>
          <ul className="grid gap-1 sm:grid-cols-2">
            {unchosen.map((key) => (
              <li key={key}>
                <label className="flex items-center gap-2 text-xs" title={COLUMN_META[key].hint}>
                  <input
                    type="checkbox"
                    checked={false}
                    onChange={(event) => toggle(key, event.target.checked)}
                    aria-label={`Show ${COLUMN_META[key].label}`}
                    className="size-3.5 accent-brand"
                  />
                  {COLUMN_META[key].label}
                </label>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={pending || chosen.length === 0}>
          {set ? `Save ${set.name}` : "Save column set"}
        </Button>
        {set ? (
          <>
            <Button
              type="submit"
              size="sm"
              variant="outline"
              name="save_as_new"
              value="1"
              disabled={pending || chosen.length === 0}
            >
              Save as new set
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="text-negative"
              disabled={deleting}
              onClick={() =>
                startDelete(async () => {
                  const result = await deleteColumnSetAction(set.id);
                  setDeleteError(result.error ?? null);
                  router.refresh();
                })
              }
            >
              Delete {set.name}
            </Button>
          </>
        ) : null}
        {state.error || deleteError ? (
          <p className="text-xs text-negative" role="alert">
            {state.error ?? deleteError}
          </p>
        ) : state.message ? (
          <output className="text-xs text-text-secondary">{state.message}</output>
        ) : null}
      </div>
    </form>
  );
}
