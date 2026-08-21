/**
 * Server-side environment guards.
 *
 * `INTERNAL_API_TOKEN` signs the web -> api bridge JWT, and FastAPI's
 * `require_user_id` trusts the `sub` claim as the user id. The dev default is
 * committed to this repository, so if it ever reached production anyone could
 * mint a token for any user and read or modify their portfolio.
 *
 * `render.yaml` and Vercel both require these to be set by hand, which is
 * exactly the kind of step that gets missed — so we fail loudly at module load
 * rather than failing open at request time. The API enforces the mirror of
 * this in `settings.py`.
 */

import "server-only";

const DEV_DEFAULTS: Record<string, string> = {
  INTERNAL_API_TOKEN: "dev-internal-token-change-me",
  AUTH_SECRET: "dev-secret-change-me",
};

function isProduction(): boolean {
  // `next build` runs page-data collection with NODE_ENV=production, but a
  // build is not a deploy: CI builds with the committed dev defaults and must
  // keep working. Only enforce at runtime.
  if (process.env.NEXT_PHASE === "phase-production-build") return false;
  // Vercel sets VERCEL_ENV; everything else falls back to NODE_ENV.
  return (process.env.VERCEL_ENV ?? process.env.NODE_ENV) === "production";
}

/**
 * Read a required server secret, refusing the committed dev default in production.
 */
export function requireSecret(name: keyof typeof DEV_DEFAULTS): string {
  const value = process.env[name];

  if (!isProduction()) {
    return value ?? DEV_DEFAULTS[name];
  }

  if (!value) {
    throw new Error(
      `${name} is not set. It is required in production — generate one with \`openssl rand -base64 32\`.`,
    );
  }
  if (value === DEV_DEFAULTS[name]) {
    throw new Error(
      `${name} is still set to the development default published in this repository. Set it to a real secret before deploying.`,
    );
  }
  return value;
}
