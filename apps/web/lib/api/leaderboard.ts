import "server-only";

import { apiGet } from "./client";
import { authedGet, authedPatch } from "./server";

export type LeaderboardEntry = {
  rank: number;
  user_id: number;
  username: string;
  return_pct: number;
  portfolio_value: string;
};

export type UserProfile = {
  user_id: number;
  public_profile: boolean;
  display_currency: string;
};

export type ProfilePatch = {
  public_profile?: boolean;
  display_currency?: string;
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
