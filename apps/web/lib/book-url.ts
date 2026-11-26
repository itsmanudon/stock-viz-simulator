/**
 * Book context in the URL (A5.2). Pure and client-safe: the switcher, page
 * links and the server loader (`lib/book-context.ts`) all use these.
 *
 * The rule:
 * - The selected book is URL state: `?book=<id>` or `?book=all` on the book
 *   pages (`BOOK_PAGES`). Absent means the user's default book.
 * - The switcher also writes a `sv_book` cookie. It is a convenience only: a
 *   book page opened without `?book=` redirects to the remembered book when
 *   that book still exists (and to `all` only where All books is allowed);
 *   anything else is ignored. Nothing needs the cookie.
 * - Links between book pages carry `?book=` (`withBookHref`).
 * - "All books" is read-only: the portfolio, dashboard, trade, trades and
 *   orders pages show it, and every trade ticket is disabled there.
 */

export type BookRef = number | "all";

/** Pages that read `?book=`; the switcher keeps you on them when you switch. */
export const BOOK_PAGES = [
  "/dashboard",
  "/portfolio",
  "/trade",
  "/orders",
  "/trades",
  "/settings",
] as const;

/**
 * Book pages that also show "All books" (read-only: the trade page shows the
 * combined account with its ticket disabled). Settings is per book only.
 */
export const ALL_BOOKS_PAGES = [
  "/dashboard",
  "/portfolio",
  "/trade",
  "/orders",
  "/trades",
] as const;

export const BOOK_COOKIE = "sv_book";
export const BOOK_COOKIE_MAX_AGE = 60 * 60 * 24 * 180;

/** `"all"`, a positive integer id, or null for anything else. */
export function parseBookParam(raw: string | string[] | null | undefined): BookRef | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value == null) return null;
  if (value === "all") return "all";
  if (!/^[1-9][0-9]{0,15}$/.test(value)) return null;
  return Number(value);
}

export function isBookPage(pathname: string): boolean {
  return BOOK_PAGES.some((page) => pathname === page || pathname.startsWith(`${page}/`));
}

export function allowsAllBooks(pathname: string): boolean {
  return ALL_BOOKS_PAGES.some((page) => pathname === page);
}

/**
 * `href` with `book=` set (or removed for null), keeping its other query
 * parameters and hash. Only book pages get the parameter.
 */
export function withBookHref(href: string, book: BookRef | null | undefined): string {
  const [beforeHash, hash = ""] = href.split("#", 2);
  const [path, query = ""] = beforeHash.split("?", 2);
  if (!isBookPage(path)) return href;
  const params = new URLSearchParams(query);
  if (book == null || (book === "all" && !allowsAllBooks(path))) params.delete("book");
  else params.set("book", String(book));
  const qs = params.toString();
  return `${path}${qs ? `?${qs}` : ""}${hash ? `#${hash}` : ""}`;
}

/** What a book row needs for the switcher and the tickets. */
export type BookSummary = {
  id: number;
  name: string;
  kind: "paper" | "imported";
  is_default: boolean;
  base_currency: string;
  holder_kind: "self" | "family" | "huf";
  holder_label?: string | null;
  archived_at?: string | null;
  writable: boolean;
};

export const HOLDER_LABELS: Record<BookSummary["holder_kind"], string> = {
  self: "Self",
  family: "Family",
  huf: "HUF",
};

/** "Self", "Family · Asha", "HUF · Jariwala HUF". */
export function holderText(book: Pick<BookSummary, "holder_kind" | "holder_label">): string {
  const kind = HOLDER_LABELS[book.holder_kind] ?? "Self";
  return book.holder_label ? `${kind} · ${book.holder_label}` : kind;
}

/**
 * Why a ticket can't trade into the selection, or null when it can. The API
 * refuses the same cases (409); the ticket says so before the user tries.
 */
export function tradeBlockReason(selection: BookSummary | "all" | null): string | null {
  if (selection === "all") {
    return "All books is a read-only view. Choose one paper book to trade.";
  }
  if (selection == null) return null;
  if (selection.archived_at) {
    return `${selection.name} is archived. Unarchive it in Settings to trade in it again.`;
  }
  if (selection.kind === "imported") {
    return `${selection.name} is an imported book: it holds a broker's trades and takes no paper orders.`;
  }
  if (!selection.writable) return `${selection.name} takes no trades.`;
  return null;
}

/** The label the switcher button shows. */
export function selectionLabel(selection: BookSummary | "all" | null): string {
  if (selection === "all") return "All books";
  return selection?.name ?? "Default book";
}

/** A single book id from `?book=` (never "all"), else null: for per-book routes. */
export function bookIdParam(raw: string | string[] | null | undefined): number | null {
  const ref = parseBookParam(raw);
  return typeof ref === "number" ? ref : null;
}

/**
 * The `book_id` a ticket form posts (A5.2): a positive id, else null (the
 * default book). Server actions pass it as `?book=`.
 */
export function bookIdFromForm(formData: FormData): number | null {
  const raw = formData.get("book_id");
  return typeof raw === "string" ? bookIdParam(raw) : null;
}

/**
 * The book proxy.ts should redirect a book page to, from the `sv_book`
 * cookie, or null for no redirect: not a book page, a `?book=` already
 * there, no usable cookie, or "all" where All books is not offered.
 */
export function rememberedBookRedirect(
  pathname: string,
  hasBookParam: boolean,
  cookie: string | null | undefined,
): BookRef | null {
  if (hasBookParam || !isBookPage(pathname)) return null;
  const remembered = parseBookParam(cookie);
  if (remembered === "all" && !allowsAllBooks(pathname)) return null;
  return remembered;
}
