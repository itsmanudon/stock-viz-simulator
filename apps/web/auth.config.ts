/**
 * Edge-runtime-safe NextAuth config.
 *
 * The middleware/proxy runs on the Edge runtime, which can't import Node's
 * ``crypto`` (used by bcryptjs). So the providers list — which calls
 * bcrypt.compare in its ``authorize`` callback — lives in ``auth.ts`` and is
 * NOT included here. This config has enough to read the JWT session cookie,
 * which is all middleware needs.
 */

import type { NextAuthConfig } from "next-auth";

export const authConfig: NextAuthConfig = {
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [],
  callbacks: {
    jwt({ token, user }) {
      if (user?.id) token.sub = user.id;
      return token;
    },
    session({ session, token }) {
      if (token.sub) session.user.id = token.sub;
      return session;
    },
  },
};
