/**
 * Augment the NextAuth ``Session`` type with our custom fields.
 *
 * We thread the DB user id through to the session so server components can
 * look up portfolios/watchlists keyed by user.id without a fresh query.
 */

import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
    } & DefaultSession["user"];
  }
}
