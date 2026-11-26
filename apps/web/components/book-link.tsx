"use client";

/**
 * A `next/link` that carries the page's `?book=` (A5.2) to another book page,
 * so links between the portfolio, trade, orders, trades and dashboard keep
 * the selected book. Other hrefs pass through unchanged.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ComponentProps } from "react";

import { parseBookParam, withBookHref } from "@/lib/book-url";

type Props = Omit<ComponentProps<typeof Link>, "href"> & { href: string };

export function BookLink({ href, ...props }: Props) {
  const book = parseBookParam(useSearchParams()?.get("book"));
  return <Link href={book == null ? href : withBookHref(href, book)} {...props} />;
}

/** The current page's book from the URL, for client code that builds hrefs. */
export function useUrlBook() {
  return parseBookParam(useSearchParams()?.get("book"));
}
