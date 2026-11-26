"use client";

/**
 * /watchlist list switcher and list management (A2.5, M4.6).
 *
 * `ListTabs` is a row of links (`?list=<id>`), so the open list is URL state
 * and each tab works without JavaScript. `ListManager` creates, renames,
 * recolours, reorders (Move left / Move right buttons, keyboard reachable),
 * makes default and deletes the open list; delete asks once more, naming
 * the list and how many symbols go with it.
 */

import { ChevronLeft, ChevronRight, Plus, Star } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState, useTransition } from "react";

import {
  type ListActionState,
  createListAction,
  deleteListAction,
  makeDefaultListAction,
  moveListAction,
  updateListAction,
} from "@/app/(product)/(authed)/watchlist/actions";
import { Button } from "@/components/ui/button";
import type { WatchlistList } from "@/lib/api/watchlist";
import { cn } from "@/lib/utils";
import { LIST_COLOURS, listColourVar } from "@/lib/watchlist-columns";

export function ListDot({ colour, className }: { colour: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2.5 shrink-0 rounded-full", className)}
      style={{ backgroundColor: listColourVar(colour) }}
    />
  );
}

export function listHref(id: number, extra: Record<string, string | undefined> = {}): string {
  const params = new URLSearchParams({ list: String(id) });
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  return `/watchlist?${params.toString()}`;
}

export function ListTabs({ lists, activeId }: { lists: WatchlistList[]; activeId: number }) {
  return (
    <nav aria-label="Watchlists" className="-mx-1 overflow-x-auto px-1">
      <ul className="flex min-w-max items-center gap-1.5">
        {lists.map((list) => {
          const active = list.id === activeId;
          return (
            <li key={list.id}>
              <Link
                href={listHref(list.id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-sm transition-colors",
                  active
                    ? "border-brand/60 bg-surface-secondary text-foreground"
                    : "border-border-muted text-text-secondary hover:bg-surface-hover hover:text-foreground",
                )}
              >
                <ListDot colour={list.colour} />
                <span className="max-w-[12rem] truncate">{list.name}</span>
                {list.is_default ? (
                  <Star
                    className="size-3 fill-current text-text-tertiary"
                    aria-label="Default list"
                  />
                ) : null}
                <span className="font-mono text-2xs text-text-tertiary">{list.item_count}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function ColourChoice({ name, value, legend }: { name: string; value: string; legend: string }) {
  return (
    <fieldset className="flex flex-wrap items-center gap-1.5">
      <legend className="mb-1 block text-xs font-medium text-text-secondary">{legend}</legend>
      {LIST_COLOURS.map((colour) => (
        <label
          key={colour.key}
          className="relative inline-grid size-7 cursor-pointer place-items-center rounded-full border border-border-muted has-[:checked]:border-foreground has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
          title={colour.label}
        >
          <input
            type="radio"
            name={name}
            value={colour.key}
            defaultChecked={colour.key === value}
            className="sr-only"
            aria-label={colour.label}
          />
          <ListDot colour={colour.key} className="size-3.5" />
        </label>
      ))}
    </fieldset>
  );
}

function Feedback({ state }: { state: ListActionState }) {
  if (state.error) {
    return (
      <p className="text-xs text-negative" role="alert">
        {state.error}
      </p>
    );
  }
  if (state.message) {
    return <output className="text-xs text-text-secondary">{state.message}</output>;
  }
  return null;
}

export function CreateListForm({ onCreated }: { onCreated?: (id: number) => void }) {
  const router = useRouter();
  const [state, action, pending] = useActionState<ListActionState, FormData>(createListAction, {});
  useEffect(() => {
    if (state.listId) {
      onCreated?.(state.listId);
      router.push(listHref(state.listId));
    }
  }, [state.listId, onCreated, router]);
  return (
    <form action={action} className="grid gap-3" aria-label="New list">
      <label className="text-xs">
        <span className="mb-1 block font-medium text-text-secondary">List name</span>
        <input
          name="name"
          required
          maxLength={64}
          placeholder="Earnings watch"
          className="flex h-9 w-full rounded-sm border border-input bg-transparent px-3 text-sm"
        />
      </label>
      <ColourChoice name="colour" value="aqua" legend="Colour" />
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Creating…" : "Create list"}
        </Button>
        <Feedback state={state} />
      </div>
    </form>
  );
}

export function ListManager({
  lists,
  active,
}: {
  lists: WatchlistList[];
  active: WatchlistList;
}) {
  const router = useRouter();
  const [open, setOpen] = useState<"none" | "new" | "edit">("none");
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<ListActionState>({});
  const [busy, startTransition] = useTransition();
  const [editState, editAction, editing] = useActionState<ListActionState, FormData>(
    updateListAction,
    {},
  );
  const index = lists.findIndex((list) => list.id === active.id);

  function act(work: () => Promise<ListActionState>, after?: () => void) {
    startTransition(async () => {
      const outcome = await work();
      setResult(outcome);
      if (!outcome.error) {
        after?.();
        router.refresh();
      }
    });
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-expanded={open === "new"}
          aria-controls="watchlist-new-list"
          onClick={() => setOpen(open === "new" ? "none" : "new")}
        >
          <Plus className="size-3.5" aria-hidden />
          New list
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-expanded={open === "edit"}
          aria-controls="watchlist-edit-list"
          onClick={() => setOpen(open === "edit" ? "none" : "edit")}
        >
          Edit {active.name}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy || index <= 0}
          onClick={() => act(() => moveListAction(active.id, -1))}
          aria-label={`Move ${active.name} left`}
          title="Move left"
        >
          <ChevronLeft className="size-4" aria-hidden />
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy || index < 0 || index >= lists.length - 1}
          onClick={() => act(() => moveListAction(active.id, 1))}
          aria-label={`Move ${active.name} right`}
          title="Move right"
        >
          <ChevronRight className="size-4" aria-hidden />
        </Button>
        {active.is_default ? (
          <span className="text-xs text-text-tertiary">
            Default list: the stock page star and the dashboard use it.
          </span>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => act(() => makeDefaultListAction(active.id))}
          >
            Make default
          </Button>
        )}
        <Feedback state={result} />
      </div>

      {open === "new" ? (
        <div id="watchlist-new-list" className="rounded-md border border-border-muted p-3">
          <CreateListForm onCreated={() => setOpen("none")} />
        </div>
      ) : null}

      {open === "edit" ? (
        <div
          id="watchlist-edit-list"
          className="grid gap-4 rounded-md border border-border-muted p-3"
        >
          <form action={editAction} className="grid gap-3" aria-label={`Edit ${active.name}`}>
            <input type="hidden" name="watchlist_id" value={active.id} />
            <label className="text-xs">
              <span className="mb-1 block font-medium text-text-secondary">Name</span>
              <input
                name="name"
                required
                maxLength={64}
                defaultValue={active.name}
                className="flex h-9 w-full max-w-sm rounded-sm border border-input bg-transparent px-3 text-sm"
              />
            </label>
            <ColourChoice name="colour" value={active.colour} legend="Colour" />
            <div className="flex items-center gap-3">
              <Button type="submit" size="sm" disabled={editing}>
                {editing ? "Saving…" : "Save list"}
              </Button>
              <Feedback state={editState} />
            </div>
          </form>
          <div className="border-t border-border-muted pt-3">
            {confirming ? (
              <fieldset className="flex flex-wrap items-center gap-2" aria-label="Confirm delete">
                <p className="text-sm">
                  Delete {active.name}
                  {active.item_count
                    ? ` and its ${active.item_count} symbol${active.item_count === 1 ? "" : "s"}`
                    : ""}
                  ?{" "}
                  {lists.length === 1
                    ? "It is your only list, so an empty Default list takes its place."
                    : active.is_default
                      ? "The next list becomes your default."
                      : ""}
                </p>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    act(
                      () => deleteListAction(active.id),
                      () => router.push("/watchlist"),
                    )
                  }
                >
                  Delete list
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirming(false)}
                >
                  Cancel
                </Button>
              </fieldset>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="text-negative"
                onClick={() => setConfirming(true)}
              >
                Delete {active.name}…
              </Button>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
