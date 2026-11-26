import "server-only";

/**
 * `/v1/books` (A5.1): a user's books. Every book-scoped route also takes
 * `?book=<id>`; without it the API uses the default book, so the existing
 * pages keep working unchanged. The switcher that sets `?book=` is A5.2.
 */

import type { components } from "./schema";
import { authedDelete, authedGet, authedPatch, authedPost } from "./server";

export type Book = components["schemas"]["BookOut"];
export type Books = components["schemas"]["BooksOut"];
export type BookInput = components["schemas"]["BookIn"];
export type BookPatch = components["schemas"]["BookPatch"];

/** Append `book=<id>` to an API path when a book is chosen; unchanged otherwise. */
export function withBook(path: string, book?: number | null): string {
  if (book == null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}book=${encodeURIComponent(String(book))}`;
}

export function listBooks(): Promise<Books> {
  return authedGet<Books>("/v1/books");
}

export function createBook(body: BookInput): Promise<Book> {
  return authedPost<Book>("/v1/books", body);
}

export function updateBook(id: number, body: BookPatch): Promise<Book> {
  return authedPatch<Book>(`/v1/books/${id}`, body);
}

export function deleteBook(id: number): Promise<void> {
  return authedDelete(`/v1/books/${id}`);
}
