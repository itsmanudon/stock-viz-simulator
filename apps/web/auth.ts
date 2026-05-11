/**
 * NextAuth v5 configuration.
 *
 * Phase 3 ships with the credentials provider only — email + bcrypt against
 * the shared Postgres ``users`` table. Sessions are JWT (not DB-backed) so
 * we don't need an adapter; the trade-off is no server-side session
 * invalidation, which is fine while the user base is just us.
 *
 * Exports:
 *  - ``auth``        — get the current session in server components / route
 *                       handlers.
 *  - ``signIn`` /``signOut`` — programmatic auth flows in server actions.
 *  - ``handlers``    — mounted at ``app/api/auth/[...nextauth]/route.ts``.
 */

import bcrypt from "bcryptjs";
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { z } from "zod";

import { findUserByEmail } from "@/lib/users";

const CredentialsSchema = z.object({
  email: z.email().max(320),
  password: z.string().min(8).max(128),
});

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(raw) {
        const parsed = CredentialsSchema.safeParse(raw);
        if (!parsed.success) return null;

        const user = await findUserByEmail(parsed.data.email);
        if (!user || !user.password_hash) return null;

        const ok = await bcrypt.compare(parsed.data.password, user.password_hash);
        if (!ok) return null;

        return {
          id: String(user.id),
          email: user.email,
          name: user.name,
          image: user.image,
        };
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      // Stamp the DB user id onto the token at sign-in time so server-side
      // code can look up portfolios/watchlists without a second round-trip.
      if (user?.id) token.sub = user.id;
      return token;
    },
    session({ session, token }) {
      if (token.sub) session.user.id = token.sub;
      return session;
    },
  },
});
