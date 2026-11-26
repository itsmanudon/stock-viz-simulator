"use client";

/**
 * Putting symbols on lists from outside /watchlist (A2.5, M4.6).
 *
 * - `AddToListMenu`: the stock page's "Lists…" disclosure beside the
 *   one-click star (which still adds to the default list). One checkbox per
 *   list; ticking adds, unticking removes, at once.
 * - `BulkAddToWatchlist`: the screener's bulk action. In `selected` mode it
 *   reads the ticked `tickers` checkboxes of the form it sits in (the
 *   Compare form); in `all` mode it adds the tickers it is given (the phone
 *   cards, which have no checkboxes). Pick a list, or name a new one.
 */

import { ListPlus } from "lucide-react";
import Link from "next/link";
import { useRef, useState, useTransition } from "react";

import {
  type ListActionState,
  bulkAddAction,
  setListMembershipAction,
} from "@/app/(product)/(authed)/watchlist/actions";
import { Button } from "@/components/ui/button";
import { ListDot } from "@/components/watchlist-lists";

export type ListChoice = { id: number; name: string; colour: string; contains?: boolean | null };

export function AddToListMenu({ ticker, lists }: { ticker: string; lists: ListChoice[] }) {
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState<Record<number, boolean>>(() =>
    Object.fromEntries(lists.map((list) => [list.id, Boolean(list.contains)])),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const panelId = `add-to-list-${ticker}`;

  return (
    <div className="relative">
      <Button
        type="button"
        size="sm"
        variant="outline"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Add ${ticker} to a list`}
        title="Add to list"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <ListPlus className="h-4 w-4" aria-hidden />
        <span className="ml-1.5 hidden sm:inline">Add to list…</span>
      </Button>
      {open ? (
        <fieldset
          id={panelId}
          className="absolute right-0 z-30 mt-2 grid w-64 gap-1 rounded-md border border-border-muted bg-surface-elevated p-3 shadow-lg"
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
          }}
        >
          <legend className="sr-only">Lists holding {ticker}</legend>
          <p className="mb-1 text-xs font-medium text-text-secondary">Lists holding {ticker}</p>
          {lists.map((list) => (
            <label
              key={list.id}
              className="flex items-center gap-2 rounded-sm px-1 py-1 text-sm hover:bg-surface-hover"
            >
              <input
                type="checkbox"
                checked={Boolean(on[list.id])}
                disabled={pending}
                onChange={(event) => {
                  const next = event.target.checked;
                  setOn((now) => ({ ...now, [list.id]: next }));
                  startTransition(async () => {
                    const result = await setListMembershipAction(list.id, ticker, next);
                    if (result.error) {
                      setError(result.error);
                      setOn((now) => ({ ...now, [list.id]: !next }));
                    } else {
                      setError(null);
                    }
                  });
                }}
                className="size-4 accent-brand"
              />
              <ListDot colour={list.colour} />
              <span className="truncate">{list.name}</span>
            </label>
          ))}
          {error ? (
            <p className="text-xs text-negative" role="alert">
              {error}
            </p>
          ) : null}
          <Link href="/watchlist" className="mt-1 text-xs text-text-secondary hover:underline">
            Manage lists
          </Link>
        </fieldset>
      ) : null}
    </div>
  );
}

const NEW = "new";

export function BulkAddToWatchlist({
  lists,
  mode,
  tickers = [],
}: {
  lists: ListChoice[];
  mode: "selected" | "all";
  tickers?: string[];
}) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [target, setTarget] = useState<string>(lists[0] ? String(lists[0].id) : NEW);
  const [newName, setNewName] = useState("");
  const [state, setState] = useState<ListActionState>({});
  const [pending, startTransition] = useTransition();

  function submit() {
    const picked =
      mode === "all"
        ? tickers
        : Array.from(
            buttonRef.current?.form?.querySelectorAll<HTMLInputElement>(
              'input[type="checkbox"][name="tickers"]:checked',
            ) ?? [],
          ).map((box) => box.value);
    const data = new FormData();
    for (const ticker of picked) data.append("tickers", ticker);
    if (target === NEW) data.set("new_list", newName);
    else data.set("watchlist_id", target);
    startTransition(async () => setState(await bulkAddAction({}, data)));
  }

  const label = mode === "all" ? `Add these ${tickers.length} to a list` : "Add selected to list";

  return (
    <fieldset className="flex flex-wrap items-center gap-2 text-xs" aria-label="Add to watchlist">
      <label className="flex items-center gap-1.5">
        <span className="text-text-secondary">List</span>
        <select
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          className="h-8 rounded-sm border border-input bg-transparent px-2 text-xs"
          aria-label="Watchlist to add to"
        >
          {lists.map((list) => (
            <option key={list.id} value={list.id}>
              {list.name}
            </option>
          ))}
          <option value={NEW}>New list…</option>
        </select>
      </label>
      {target === NEW ? (
        <input
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          maxLength={64}
          placeholder="New list name"
          aria-label="New list name"
          className="h-8 w-36 rounded-sm border border-input bg-transparent px-2 text-xs"
        />
      ) : null}
      <Button
        ref={buttonRef}
        type="button"
        size="sm"
        variant="outline"
        disabled={pending}
        onClick={submit}
      >
        {pending ? "Adding…" : label}
      </Button>
      {state.error ? (
        <span className="text-negative" role="alert">
          {state.error}
        </span>
      ) : state.message ? (
        <output className="text-text-secondary">
          {state.message}{" "}
          {state.listId ? (
            <Link href={`/watchlist?list=${state.listId}`} className="underline">
              Open list
            </Link>
          ) : null}
        </output>
      ) : null}
    </fieldset>
  );
}
