/**
 * Route protection for paper-trading pages.
 *
 * Next.js 16 renamed ``middleware.ts`` to ``proxy.ts``; functionally
 * identical. Runs on the Edge runtime, so we use the providers-free
 * ``authConfig`` — importing ``auth.ts`` here would drag bcryptjs into the
 * Edge bundle.
 */

import NextAuth from "next-auth";
import { NextResponse } from "next/server";

import { authConfig } from "@/auth.config";
import { BOOK_COOKIE, rememberedBookRedirect } from "@/lib/book-url";

const { auth: proxyAuth } = NextAuth(authConfig);

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/trade",
  "/portfolio",
  "/trades",
  "/watchlist",
  "/alerts",
  "/notifications",
  "/settings",
  "/orders",
  "/replay",
  "/drills",
  "/earnings",
  "/backtest/runs",
  "/setups",
];

export default proxyAuth((req) => {
  const path = req.nextUrl.pathname;
  const isProtected = PROTECTED_PREFIXES.some((prefix) => path.startsWith(prefix));
  if (isProtected && !req.auth) {
    const promptUrl = new URL("/sign-in-required", req.url);
    promptUrl.searchParams.set("callbackUrl", path);
    return NextResponse.redirect(promptUrl);
  }
  // A5.2: a book page opened without `?book=` goes to the remembered book (the
  // switcher's `sv_book` cookie) with a real redirect, before the page
  // renders. Done in a page it arrived after the streamed page had loaded, as
  // a client navigation: the default book showed first and the next
  // navigation could be aborted. loadBookContext still checks the book is
  // the user's (an unknown id falls back to the default).
  const remembered = req.auth
    ? rememberedBookRedirect(
        path,
        req.nextUrl.searchParams.has("book"),
        req.cookies.get(BOOK_COOKIE)?.value,
      )
    : null;
  if (remembered !== null) {
    const target = req.nextUrl.clone();
    target.searchParams.set("book", String(remembered));
    return NextResponse.redirect(target);
  }
  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next|api/auth|api/health|_static|favicon.ico).*)"],
};
