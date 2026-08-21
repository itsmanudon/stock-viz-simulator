/**
 * NextAuth v5 configuration — full Node-runtime version.
 *
 * The credentials provider's ``authorize`` callback uses bcryptjs (Node
 * ``crypto``) so this module can't be imported from Edge contexts. Middleware
 * uses ``auth.config.ts`` instead, which is providers-free.
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
import Google from "next-auth/providers/google";
import { z } from "zod";

import { authConfig } from "@/auth.config";
import { requireSecret } from "@/lib/env";
import { findOrCreateOAuthUser, findUserByEmail } from "@/lib/users";

// Fail at module load rather than issuing sessions signed with the dev secret
// that is committed to this repository. NextAuth reads AUTH_SECRET from the
// environment itself; this only validates it.
requireSecret("AUTH_SECRET");

const CredentialsSchema = z.object({
  email: z.email().max(320),
  password: z.string().min(8).max(128),
});

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Google,
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
    ...authConfig.callbacks,
    async jwt({ token, user, account }) {
      // Credentials: authorize() already set user.id to our DB id
      if (account?.provider === "credentials") {
        if (user?.id) token.sub = user.id;
        return token;
      }
      // OAuth: look up or create the user row and store our DB id in the token
      if (account && user?.email) {
        const dbUser = await findOrCreateOAuthUser({
          email: user.email,
          name: user.name ?? null,
          image: user.image ?? null,
        });
        token.sub = String(dbUser.id);
        token.name = dbUser.name;
        token.picture = dbUser.image;
      }
      return token;
    },
  },
});
