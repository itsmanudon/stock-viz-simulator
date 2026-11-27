/**
 * /portfolio/import?book=<id> — A5.3, A6.11: import a broker's tradebook CSV
 * (Zerodha, Dhan, Fyers, Upstox, Angel One, Groww, or any file through your
 * own column map; a USD book takes a US broker's file that way) into an
 * imported book. Preview, then Confirm import; the batch history, opening
 * lots and sells waiting for one. A paper book (or All books) explains where
 * imports go instead.
 */

import type { Metadata } from "next";

import { BookLink as Link } from "@/components/book-link";
import { MetaChip, PageEmptyState, PageHeader } from "@/components/page-header";
import { TradebookImport } from "@/components/tradebook-import";
import { Button } from "@/components/ui/button";
import { getImports } from "@/lib/api/imports";
import { loadBookContext } from "@/lib/book-context";
import { brokerLabel } from "@/lib/tradebook-import";

export const metadata: Metadata = { title: "Import tradebook" };

export default async function ImportPage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string }>;
}) {
  const params = await searchParams;
  const books = await loadBookContext(params.book, "/portfolio/import", params);
  const book = books.selected;
  const imported = book?.kind === "imported";
  const status = imported && book ? await getImports(book.id).catch(() => null) : null;
  const importedBooks = books.books.filter((b) => b.kind === "imported" && !b.archived_at);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:py-7">
      <PageHeader
        title="Import tradebook"
        description="Bring a broker's tradebook (CSV) into an imported book: holdings and realized P&L, with estimated charges for Indian trades."
        meta={
          book ? (
            <span className="flex flex-wrap items-center gap-2">
              <MetaChip>Book: {book.name}</MetaChip>
              {imported ? (
                <MetaChip>
                  {brokerLabel(book.broker)} · {book.base_currency}
                </MetaChip>
              ) : null}
            </span>
          ) : null
        }
        actions={
          imported ? (
            <Button asChild variant="outline" size="sm">
              <Link href="/portfolio">Back to Portfolio</Link>
            </Button>
          ) : null
        }
      />
      <div className="mt-6">
        {!book || !imported ? (
          <PageEmptyState
            title={book ? `${book.name} is a paper book` : "Choose a book"}
            action={
              <div className="flex flex-wrap gap-2">
                {importedBooks.map((b) => (
                  <Button key={b.id} asChild size="sm" variant="outline">
                    <a href={`/portfolio/import?book=${b.id}`}>Import into {b.name}</a>
                  </Button>
                ))}
                <Button asChild size="sm" variant={importedBooks.length ? "ghost" : "default"}>
                  <a href="/settings#books">Create an Imported Book</a>
                </Button>
              </div>
            }
          >
            Broker trades go into an imported book, which holds them without cash and takes no paper
            orders. Pick one in the switcher, or create one in Settings → Books.
          </PageEmptyState>
        ) : book.archived_at ? (
          <PageEmptyState title={`${book.name} is archived`}>
            Unarchive it in Settings → Books to import into it.
          </PageEmptyState>
        ) : book.base_currency !== "INR" && book.base_currency !== "USD" ? (
          <PageEmptyState title={`${book.name} is in ${book.base_currency}`}>
            Imports go into an INR book (Indian brokers) or a USD book (US brokers, with your own
            column map).
          </PageEmptyState>
        ) : status ? (
          <TradebookImport bookId={book.id} status={status} />
        ) : (
          <PageEmptyState title="Imports could not be loaded">
            The server did not answer. Reload the page to try again.
          </PageEmptyState>
        )}
      </div>
    </div>
  );
}
