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
 * The API already caches this for an hour server-side; `revalidateSeconds`
 * additionally keeps the marketing page from re-requesting it per visitor.
 */
export function getLeaderboard(revalidateSeconds?: number): Promise<LeaderboardEntry[]> {
  return apiGet<LeaderboardEntry[]>(
    "/v1/leaderboard",
    revalidateSeconds === undefined ? undefined : { revalidateSeconds, tags: ["leaderboard"] },
  );
}

export function getProfile(): Promise<UserProfile> {
  return authedGet<UserProfile>("/v1/profile");
}

export function patchProfile(body: ProfilePatch): Promise<UserProfile> {
  return authedPatch<UserProfile>("/v1/profile", body);
}
