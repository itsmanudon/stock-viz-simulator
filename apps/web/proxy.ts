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

const { auth: proxyAuth } = NextAuth(authConfig);

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/trade",
  "/portfolio",
  "/trades",
  "/watchlist",
  "/alerts",
  "/settings",
  "/orders",
  "/replay",
  "/earnings",
];

export default proxyAuth((req) => {
  const path = req.nextUrl.pathname;
  const isProtected = PROTECTED_PREFIXES.some((prefix) => path.startsWith(prefix));
  if (isProtected && !req.auth) {
    const promptUrl = new URL("/sign-in-required", req.url);
    promptUrl.searchParams.set("callbackUrl", path);
    return NextResponse.redirect(promptUrl);
  }
  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next|api/auth|api/health|_static|favicon.ico).*)"],
};
