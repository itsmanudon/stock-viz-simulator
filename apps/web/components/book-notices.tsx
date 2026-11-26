import { Info } from "lucide-react";

import { BookLink } from "@/components/book-link";
import { ArchivedBadge, BookKindBadge } from "@/components/book-switcher";
import type { Book } from "@/lib/api/books";
import type { CombinedInfo } from "@/lib/api/trading";
import { formatCurrency } from "@/lib/portfolio-view-model";

/**
 * A5.2 All books: which books the figure sums, each in the display currency,
 * how the rates were taken, and what stays per book. Each row opens the book.
 */
export function CombinedBooksPanel({
  combined,
  currency,
  total,
}: {
  combined: CombinedInfo;
  currency: string;
  total: string;
}) {
  return (
    <section
      aria-labelledby="combined-books-heading"
      className="mt-5 rounded-xl border border-border-muted bg-card"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-muted px-4 py-3">
        <h2 id="combined-books-heading" className="text-sm font-semibold">
          All books · {combined.books.length} books in {currency}
        </h2>
        <p className="text-2xs text-text-tertiary">Read-only. Trade from one book.</p>
      </div>
      <ul className="divide-y divide-border-muted">
        {combined.books.map((book) => {
          const share = Number(total) ? (Number(book.total_value) / Number(total)) * 100 : null;
          return (
            <li key={book.id}>
              <BookLink
                href={`/portfolio?book=${book.id}`}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5 text-sm hover:bg-surface-hover"
              >
                <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="truncate font-medium">{book.name}</span>
                  <BookKindBadge kind={book.kind} />
                  {book.archived ? <ArchivedBadge /> : null}
                  <span className="font-mono text-2xs text-text-tertiary">
                    held in {book.base_currency}
                  </span>
                </span>
                <span className="font-mono tabular-nums" data-financial>
                  {formatCurrency(book.total_value, currency)}
                  {share !== null ? (
                    <span className="ml-2 text-2xs text-text-tertiary">{share.toFixed(1)}%</span>
                  ) : null}
                </span>
              </BookLink>
            </li>
          );
        })}
      </ul>
      <div className="space-y-1.5 border-t border-border-muted px-4 py-3 text-2xs leading-relaxed text-text-tertiary">
        <p>
          Each book&apos;s value is converted to {currency} at the rate stored for that date, then
          added up. Returns leave out the money a new book or an imported buy brings in. Today uses
          the latest stored rate; {combined.fx_rule}.
        </p>
        <p>Per book only: {combined.per_book_only.join(", ")}.</p>
      </div>
    </section>
  );
}

/** Says what a non-paper or archived book can do, under the portfolio header. */
export function BookStateNotice({ book }: { book: Book | null }) {
  if (!book || (book.kind === "paper" && !book.archived_at)) return null;
  const text = book.archived_at
    ? `${book.name} is archived: you can read it, but it takes no trades or orders. Unarchive it in Settings to trade in it.`
    : book.activity && book.activity.length > 0
      ? `${book.name} is an imported book: it holds a broker's trades, values holdings only (no cash) and takes no paper orders.`
      : `${book.name} is an imported book with no imports yet. Importing a broker tradebook comes in a later batch; it takes no paper orders.`;
  return (
    <p
      role="note"
      className="mt-4 flex items-start gap-2 rounded-md border border-border-muted bg-surface-secondary/50 px-3 py-2.5 text-xs text-text-secondary"
    >
      <Info className="mt-px size-3.5 shrink-0 text-text-tertiary" aria-hidden />
      <span>{text}</span>
    </p>
  );
}

/** Stands in for a per-book panel on All books. */
export function PerBookOnly({ what }: { what: string }) {
  return (
    <p className="py-6 text-sm text-muted-foreground">
      {what} is per book. Choose a book in the switcher to see it.
    </p>
  );
}
