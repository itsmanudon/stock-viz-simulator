"use client";

/**
 * The book switcher in the product top bar (A5.2), signed in only.
 *
 * A disclosure button and a list of links, so it works with the keyboard
 * (Tab, arrow keys, Escape) and on a phone (the panel spans the width under
 * the bar). Each link carries `?book=` (`lib/book-url.ts`): on a book page it
 * keeps the page and its other parameters; elsewhere it opens the dashboard.
 * "All books" is a read-only view, offered on the pages that have one. A
 * click also remembers the choice in the `sv_book` cookie: a convenience the
 * pages use only when the URL names no book.
 */

import { BookCopy, Check, ChevronDown, Settings2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import {
  BOOK_COOKIE,
  BOOK_COOKIE_MAX_AGE,
  type BookRef,
  type BookSummary,
  allowsAllBooks,
  holderText,
  isBookPage,
  parseBookParam,
  selectionLabel,
  withBookHref,
} from "@/lib/book-url";
import { cn } from "@/lib/utils";

export function rememberBook(book: BookRef): void {
  try {
    document.cookie = `${BOOK_COOKIE}=${book}; path=/; max-age=${BOOK_COOKIE_MAX_AGE}; samesite=lax`;
  } catch {
    // A blocked cookie only loses the convenience.
  }
}

function readRemembered(): BookRef | null {
  try {
    const match = document.cookie.split("; ").find((c) => c.startsWith(`${BOOK_COOKIE}=`));
    return parseBookParam(match?.split("=")[1]);
  } catch {
    return null;
  }
}

/** Where choosing `book` goes from `pathname?query`. */
export function switchHref(pathname: string, query: string, book: BookRef): string {
  if (isBookPage(pathname)) {
    if (book === "all" && !allowsAllBooks(pathname)) return "/portfolio?book=all";
    // Journal state (a month, a day) belongs to one book: drop it on a switch.
    const params = new URLSearchParams(query);
    for (const key of ["date", "week"]) params.delete(key);
    const qs = params.toString();
    return withBookHref(`${pathname}${qs ? `?${qs}` : ""}`, book);
  }
  return withBookHref("/dashboard", book);
}

export function BookSwitcher({ books, limit }: { books: BookSummary[]; limit: number }) {
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const query = searchParams?.toString() ?? "";
  const [open, setOpen] = useState(false);
  const [remembered, setRemembered] = useState<BookRef | null>(null);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setRemembered(readRemembered()), []);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  // Close when the page changes (a link was followed).
  // biome-ignore lint/correctness/useExhaustiveDependencies: run on navigation only.
  useEffect(() => setOpen(false), [pathname, query]);

  if (books.length === 0) return null;
  const defaultBook = books.find((b) => b.is_default) ?? books[0];
  const fromUrl = isBookPage(pathname) ? parseBookParam(searchParams?.get("book")) : null;
  const ref: BookRef | null = isBookPage(pathname) ? fromUrl : (remembered ?? null);
  const selection: BookSummary | "all" =
    ref === "all" && books.length > 1 ? "all" : (books.find((b) => b.id === ref) ?? defaultBook);
  const showAll = books.length > 1;

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      buttonRef.current?.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>("[data-book-item]") ?? [],
    );
    if (items.length === 0) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "ArrowDown"
        ? items[(at + 1) % items.length]
        : items[(at - 1 + items.length) % items.length];
    next?.focus();
  }

  const label = selectionLabel(selection);
  const currency = selection === "all" ? null : selection.base_currency;

  return (
    <div ref={rootRef} className="static lg:relative" onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Book: ${label}${currency ? ` (${currency})` : ""}. Switch book`}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-9 max-w-[9.5rem] items-center gap-1.5 rounded-full border border-border-muted bg-card px-2.5 text-xs font-medium transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:max-w-[14rem]"
      >
        <BookCopy className="size-3.5 shrink-0 text-text-tertiary" aria-hidden />
        <span className="min-w-0 truncate">{label}</span>
        {currency ? (
          <span className="hidden shrink-0 font-mono text-2xs text-text-tertiary sm:inline">
            {currency}
          </span>
        ) : null}
        <ChevronDown className="size-3.5 shrink-0 text-text-tertiary" aria-hidden />
      </button>

      {open ? (
        <div
          id={panelId}
          className="absolute top-full right-3 left-3 z-40 mt-1 overflow-hidden rounded-xl border border-border-muted bg-popover text-popover-foreground shadow-lg sm:left-auto sm:w-[22rem] lg:right-0 lg:mt-2"
        >
          <p className="border-b border-border-muted px-3.5 py-2 text-2xs font-medium tracking-[0.12em] text-text-tertiary uppercase">
            Books · {books.length} of {limit}
          </p>
          <ul className="max-h-[60vh] overflow-y-auto py-1" aria-label="Books">
            {showAll ? (
              <li>
                <Link
                  data-book-item
                  href={switchHref(pathname, query, "all")}
                  onClick={() => rememberBook("all")}
                  aria-current={selection === "all" ? "true" : undefined}
                  className="flex items-start gap-2.5 px-3.5 py-2.5 text-sm outline-none hover:bg-surface-hover focus-visible:bg-surface-hover"
                >
                  <SelectedMark on={selection === "all"} />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">All books</span>
                    <span className="block text-2xs text-text-tertiary">
                      Combined in your display currency · read-only
                      {isBookPage(pathname) && !allowsAllBooks(pathname)
                        ? " · opens Portfolio"
                        : ""}
                    </span>
                  </span>
                </Link>
              </li>
            ) : null}
            {books.map((book) => (
              <li key={book.id}>
                <Link
                  data-book-item
                  href={switchHref(pathname, query, book.id)}
                  onClick={() => rememberBook(book.id)}
                  aria-current={
                    selection !== "all" && selection.id === book.id ? "true" : undefined
                  }
                  className="flex items-start gap-2.5 px-3.5 py-2.5 text-sm outline-none hover:bg-surface-hover focus-visible:bg-surface-hover"
                >
                  <SelectedMark on={selection !== "all" && selection.id === book.id} />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="min-w-0 truncate font-medium">{book.name}</span>
                      <BookKindBadge kind={book.kind} />
                      {book.archived_at ? <ArchivedBadge /> : null}
                      {book.is_default && book.name.toLowerCase() !== "default" ? (
                        <span className="text-2xs text-text-tertiary">Default</span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block text-2xs text-text-tertiary">
                      <span className="font-mono">{book.base_currency}</span> · {holderText(book)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <Link
            data-book-item
            href="/settings#books"
            className="flex items-center gap-2 border-t border-border-muted px-3.5 py-2.5 text-xs font-medium text-text-secondary outline-none hover:bg-surface-hover hover:text-foreground focus-visible:bg-surface-hover"
          >
            <Settings2 className="size-3.5" aria-hidden />
            Manage books
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function SelectedMark({ on }: { on: boolean }) {
  return (
    <span className="mt-0.5 grid size-4 shrink-0 place-items-center" aria-hidden>
      {on ? <Check className="size-3.5 text-brand" /> : null}
    </span>
  );
}

export function BookKindBadge({ kind }: { kind: BookSummary["kind"] }) {
  return (
    <span
      className={cn(
        "rounded-full border px-1.5 py-px text-3xs font-medium tracking-wide uppercase",
        kind === "imported"
          ? "border-brand/40 text-brand"
          : "border-border-muted text-text-tertiary",
      )}
    >
      {kind === "imported" ? "Imported" : "Paper"}
    </span>
  );
}

export function ArchivedBadge() {
  return (
    <span className="rounded-full border border-warning/40 px-1.5 py-px text-3xs font-medium tracking-wide text-warning uppercase">
      Archived
    </span>
  );
}
