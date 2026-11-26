import { Suspense } from "react";

import { BookSwitcher } from "@/components/book-switcher";
import { listBooks } from "@/lib/api/books";

/**
 * A5.2: loads the user's books for the top bar's switcher. Async on its own so
 * the bar stays synchronous; a failed list just hides the switcher.
 */
export async function BookSwitcherSlot() {
  const books = await listBooks().catch(() => null);
  if (!books) return null;
  return (
    <span className="mr-1">
      <Suspense fallback={null}>
        <BookSwitcher books={books.books} limit={books.limit} />
      </Suspense>
    </span>
  );
}
