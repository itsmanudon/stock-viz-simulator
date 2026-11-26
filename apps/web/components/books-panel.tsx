"use client";

/**
 * Settings → Books (A5.2). Lists the user's books with what each holds, and
 * creates, renames, moves the default, archives, unarchives and deletes them
 * through the server actions in `settings/book-actions.ts`. The API's rules
 * are explained beside each control, so a refusal is never a surprise:
 *
 * - at most `limit` (20) books, archived ones included;
 * - one default, always a paper book that is not archived;
 * - the default can't be archived, nor a book with pending orders;
 * - delete only an empty or archived book, never the default (two steps,
 *   naming what goes, then the book's name typed back).
 *
 * There is no PAN field: a book's holder is a kind and a free-text label.
 */

import Link from "next/link";
import { useActionState, useId, useState } from "react";

import {
  type BookActionState,
  bookStateAction,
  createBookAction,
  deleteBookAction,
  renameBookAction,
} from "@/app/(product)/(authed)/settings/book-actions";
import { ArchivedBadge, BookKindBadge } from "@/components/book-switcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type BookSummary, holderText } from "@/lib/book-url";
import { IMPORT_BROKERS } from "@/lib/tradebook-import";

export type BookRow = BookSummary & { activity?: readonly string[] };

const SELECT =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

const INITIAL: BookActionState = {};

export function BooksPanel({ books, limit }: { books: BookRow[]; limit: number }) {
  const full = books.length >= limit;
  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-text-tertiary">
        A book is a separate account: its own cash, currency, trades, orders, limits and journal.
        Pages show the book chosen in the top bar; All books adds them up in your display currency.{" "}
        <span className="font-medium text-text-secondary">
          {books.length} of {limit} books
        </span>
        {full ? " · the limit is reached; delete an archived book to add another." : "."}
      </p>

      <ul className="divide-y divide-border-muted rounded-lg border border-border-muted">
        {books.map((book) => (
          <BookItem key={book.id} book={book} onlyBook={books.length === 1} />
        ))}
      </ul>

      <CreateBookForm disabled={full} />
    </div>
  );
}

function Status({ state }: { state: BookActionState }) {
  if (state.error)
    return (
      <p role="alert" className="text-xs text-negative">
        {state.error}
      </p>
    );
  if (state.ok) return <output className="block text-xs text-positive">{state.ok}</output>;
  return null;
}

function BookItem({ book, onlyBook }: { book: BookRow; onlyBook: boolean }) {
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const [stateResult, stateAction, statePending] = useActionState(bookStateAction, INITIAL);
  const archived = Boolean(book.archived_at);
  const activity = book.activity ?? [];

  return (
    <li className="space-y-3 px-4 py-3" data-testid={`book-row-${book.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
            <span className="truncate">{book.name}</span>
            <BookKindBadge kind={book.kind} />
            {archived ? <ArchivedBadge /> : null}
            {book.is_default ? (
              <span className="rounded-full bg-brand/10 px-1.5 py-px text-3xs font-medium tracking-[0.02em] text-brand">
                Default
              </span>
            ) : null}
          </p>
          <p className="mt-0.5 text-xs text-text-tertiary">
            <span className="font-mono">{book.base_currency}</span> · {holderText(book)} ·{" "}
            {activity.length ? `has ${activity.join(", ")}` : "no activity yet"}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Button asChild size="sm" variant="ghost" className="h-8 rounded-full text-xs">
            <Link href={`/portfolio?book=${book.id}`}>Open</Link>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 rounded-full text-xs"
            aria-expanded={mode === "edit"}
            onClick={() => setMode(mode === "edit" ? "view" : "edit")}
          >
            Rename
          </Button>
          <form action={stateAction} className="contents">
            <input type="hidden" name="book_id" value={book.id} />
            {!book.is_default && !archived && book.kind === "paper" ? (
              <Button
                type="submit"
                name="op"
                value="default"
                size="sm"
                variant="outline"
                className="h-8 rounded-full text-xs"
                disabled={statePending}
              >
                Make default
              </Button>
            ) : null}
            {!book.is_default ? (
              <Button
                type="submit"
                name="op"
                value={archived ? "unarchive" : "archive"}
                size="sm"
                variant="outline"
                className="h-8 rounded-full text-xs"
                disabled={statePending}
              >
                {archived ? "Unarchive" : "Archive"}
              </Button>
            ) : null}
          </form>
          {!book.is_default && !onlyBook ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 rounded-full border-negative/40 text-xs text-negative hover:bg-negative/10"
              aria-expanded={mode === "delete"}
              onClick={() => setMode(mode === "delete" ? "view" : "delete")}
            >
              Delete…
            </Button>
          ) : null}
        </div>
      </div>
      <Status state={stateResult} />
      {book.is_default ? (
        <p className="text-2xs text-text-tertiary">
          The default book can't be archived or deleted. Make another paper book the default first.
        </p>
      ) : null}
      {mode === "edit" ? <RenameForm book={book} onDone={() => setMode("view")} /> : null}
      {mode === "delete" ? (
        <DeleteForm book={book} activity={activity} onCancel={() => setMode("view")} />
      ) : null}
    </li>
  );
}

function RenameForm({ book, onDone }: { book: BookRow; onDone: () => void }) {
  const id = useId();
  const [state, action, pending] = useActionState(renameBookAction, INITIAL);
  return (
    <form
      action={action}
      className="grid gap-3 rounded-md bg-surface-secondary/40 p-3 sm:grid-cols-3"
    >
      <input type="hidden" name="book_id" value={book.id} />
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-name`} className="text-xs">
          Name
        </Label>
        <Input id={`${id}-name`} name="name" defaultValue={book.name} maxLength={60} required />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-holder`} className="text-xs">
          Whose money
        </Label>
        <select
          id={`${id}-holder`}
          name="holder_kind"
          defaultValue={book.holder_kind}
          className={SELECT}
        >
          <option value="self">Self</option>
          <option value="family">Family</option>
          <option value="huf">HUF</option>
        </select>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-label`} className="text-xs">
          Holder label (optional)
        </Label>
        <Input
          id={`${id}-label`}
          name="holder_label"
          defaultValue={book.holder_label ?? ""}
          maxLength={60}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:col-span-3">
        <Button type="submit" size="sm" className="rounded-full" disabled={pending}>
          {pending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" size="sm" variant="ghost" className="rounded-full" onClick={onDone}>
          Cancel
        </Button>
        <Status state={state} />
      </div>
    </form>
  );
}

function DeleteForm({
  book,
  activity,
  onCancel,
}: {
  book: BookRow;
  activity: readonly string[];
  onCancel: () => void;
}) {
  const id = useId();
  const [typed, setTyped] = useState("");
  const [state, action, pending] = useActionState(deleteBookAction, INITIAL);
  const allowed = activity.length === 0 || Boolean(book.archived_at);
  return (
    <form
      action={action}
      className="space-y-3 rounded-md border border-negative/40 bg-negative/5 p-3 text-xs"
      aria-label={`Delete ${book.name}`}
    >
      <input type="hidden" name="book_id" value={book.id} />
      <input type="hidden" name="expected_name" value={book.name} />
      <p className="font-medium text-foreground">Delete {book.name}?</p>
      <p className="leading-relaxed text-text-secondary">
        {activity.length
          ? `This removes everything in it for good: its ${activity.join(", ")}, cash, positions, snapshots, limits and journal.`
          : "It has no activity yet: only the book and its starting cash go."}{" "}
        Other books are not touched. Backups keep deleted rows until they age out.
      </p>
      {!allowed ? (
        <p className="text-warning">
          A book with activity must be archived before it can be deleted. Archive it first.
        </p>
      ) : (
        <div className="grid gap-1.5 sm:max-w-xs">
          <Label htmlFor={`${id}-confirm`}>Type the book&apos;s name to confirm</Label>
          <Input
            id={`${id}-confirm`}
            name="confirm_name"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
          />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          size="sm"
          variant="destructive"
          className="rounded-full"
          disabled={!allowed || typed !== book.name || pending}
        >
          {pending ? "Deleting…" : "Delete book"}
        </Button>
        <Button type="button" size="sm" variant="ghost" className="rounded-full" onClick={onCancel}>
          Keep it
        </Button>
        <Status state={state} />
      </div>
    </form>
  );
}

function CreateBookForm({ disabled }: { disabled: boolean }) {
  const id = useId();
  const [state, action, pending] = useActionState(createBookAction, INITIAL);
  return (
    <form action={action} aria-labelledby={`${id}-title`} className="space-y-3">
      <h3 id={`${id}-title`} className="text-sm font-medium">
        New book
      </h3>
      <fieldset disabled={disabled || pending} className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-name`} className="text-xs">
            Name
          </Label>
          <Input id={`${id}-name`} name="name" maxLength={60} required placeholder="India growth" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-currency`} className="text-xs">
            Currency
          </Label>
          <select id={`${id}-currency`} name="base_currency" defaultValue="USD" className={SELECT}>
            <option value="USD">USD · starts with $100,000</option>
            <option value="INR">INR · starts with ₹1 crore</option>
          </select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-kind`} className="text-xs">
            Kind
          </Label>
          <select id={`${id}-kind`} name="kind" defaultValue="paper" className={SELECT}>
            <option value="paper">Paper · trades here</option>
            <option value="imported">Imported · a broker&apos;s tradebook, no paper orders</option>
          </select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-broker`} className="text-xs">
            Broker (Imported Books)
          </Label>
          <select
            id={`${id}-broker`}
            name="broker"
            defaultValue="zerodha"
            className={SELECT}
            aria-describedby={`${id}-broker-hint`}
          >
            {IMPORT_BROKERS.map((b) => (
              <option key={b.value} value={b.value}>
                {b.label}
              </option>
            ))}
          </select>
          <p id={`${id}-broker-hint`} className="text-2xs text-text-tertiary">
            An Indian broker&apos;s book is in INR. Other Broker takes the currency above: USD for a
            US broker.
          </p>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-holder`} className="text-xs">
            Whose money
          </Label>
          <select id={`${id}-holder`} name="holder_kind" defaultValue="self" className={SELECT}>
            <option value="self">Self</option>
            <option value="family">Family</option>
            <option value="huf">HUF</option>
          </select>
        </div>
        <div className="grid gap-1.5 sm:col-span-2">
          <Label htmlFor={`${id}-label`} className="text-xs">
            Holder label (optional)
          </Label>
          <Input
            id={`${id}-label`}
            name="holder_label"
            maxLength={60}
            placeholder="Mum, or Jariwala HUF"
            aria-describedby={`${id}-label-hint`}
          />
          <p id={`${id}-label-hint`} className="text-2xs text-text-tertiary">
            A name only. Don&apos;t enter a PAN: StockViz doesn&apos;t store one and refuses a label
            shaped like it.
          </p>
        </div>
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="sm" className="rounded-full" disabled={disabled || pending}>
          {pending ? "Creating…" : "Create book"}
        </Button>
        <p className="text-2xs text-text-tertiary">
          The currency is fixed after the book's first trade, order or option.
        </p>
      </div>
      <Status state={state} />
    </form>
  );
}
