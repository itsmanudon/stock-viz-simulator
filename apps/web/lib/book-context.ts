import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { type Book, listBooks } from "@/lib/api/books";
import {
  BOOK_COOKIE,
  type BookRef,
  allowsAllBooks,
  parseBookParam,
  tradeBlockReason,
  withBookHref,
} from "@/lib/book-url";

/**
 * The book a page shows (A5.2), from `?book=`, the user's default when absent.
 *
 * - `book`: the id to send to the API (`withBook`), `"all"`, or null for the
 *   default (the API's own default; the page still knows which book it is).
 * - `selected`: the book row, or null for All books (or when the list failed).
 * - An unknown or another user's id is ignored: the page shows the default
 *   book rather than a 404, and the switcher shows which one that is.
 * - Without `?book=`, a remembered `sv_book` cookie redirects to that book
 *   (convenience only; ignored when the book is gone).
 */
export type BookContext = {
  books: Book[];
  /** The book list loaded; false leaves every page on the default book. */
  listed: boolean;
  book: BookRef | null;
  selected: Book | null;
  isAll: boolean;
  /** Why the trade ticket can't trade here, or null. */
  tradeBlock: string | null;
  limit: number;
};

export async function loadBookContext(
  raw: string | string[] | undefined,
  pathname: string,
  query: Record<string, string | string[] | undefined> = {},
): Promise<BookContext> {
  const list = await listBooks().catch(() => null);
  const books = list?.books ?? [];
  const defaultBook = books.find((b) => b.is_default) ?? books[0] ?? null;
  let ref = parseBookParam(raw);

  if (raw === undefined && list) {
    const remembered = parseBookParam((await cookies()).get(BOOK_COOKIE)?.value);
    const usable =
      remembered === "all"
        ? allowsAllBooks(pathname) && books.length > 1
        : remembered != null && books.some((b) => b.id === remembered);
    if (usable && remembered !== defaultBook?.id) {
      redirect(withBookHref(hrefWith(pathname, query), remembered));
    }
  }

  if (ref === "all" && (!allowsAllBooks(pathname) || !list)) ref = null;
  if (typeof ref === "number" && !books.some((b) => b.id === ref)) ref = null;

  const isAll = ref === "all";
  const selected = isAll ? null : (books.find((b) => b.id === ref) ?? defaultBook);
  return {
    books,
    listed: Boolean(list),
    book: isAll ? "all" : typeof ref === "number" ? ref : null,
    selected,
    isAll,
    tradeBlock: tradeBlockReason(isAll ? "all" : selected),
    limit: list?.limit ?? 20,
  };
}

function hrefWith(pathname: string, query: Record<string, string | string[] | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || key === "book") continue;
    for (const v of Array.isArray(value) ? value : [value]) params.append(key, v);
  }
  const qs = params.toString();
  return `${pathname}${qs ? `?${qs}` : ""}`;
}
