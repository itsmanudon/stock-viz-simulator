import "server-only";

import { apiGet } from "./client";
import { authedGet, authedPatch } from "./server";

export type LeaderboardEntry = {
  rank: number;
  /** SR-12 (Phase 8.6): an opaque public handle; the database id is never sent. */
  handle: string;
  /** The display name the user set, else the handle; never the email. */
  username: string;
  return_pct: number;
  portfolio_value: string;
  /** Phase 4.8: portfolio_value is in the account's base currency. */
  currency?: string;
};

export type UserProfile = {
  user_id: number;
  public_profile: boolean;
  display_currency: string;
  /** SR-12: shown on the leaderboard as display_name, else public_handle. */
  public_handle?: string | null;
  display_name?: string | null;
};

export type ProfilePatch = {
  public_profile?: boolean;
  display_currency?: string;
  /** 2 to 40 characters, no "@"; an empty string clears it. */
  display_name?: string;
};

/**
 * The API rechecks profile visibility on each request. Caching this response
 * in Next would keep an opted-out user's identity visible until expiry.
 */
export function getLeaderboard(): Promise<LeaderboardEntry[]> {
  return apiGet<LeaderboardEntry[]>("/v1/leaderboard", { cache: "no-store" });
}

export function getProfile(): Promise<UserProfile> {
  return authedGet<UserProfile>("/v1/profile");
}

export function patchProfile(body: ProfilePatch): Promise<UserProfile> {
  return authedPatch<UserProfile>("/v1/profile", body);
}
