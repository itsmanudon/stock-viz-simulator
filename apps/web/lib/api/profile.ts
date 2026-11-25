import "server-only";

import { authedGet, authedPatch } from "./server";

/** The caller's display settings (`/v1/profile`). */
export type UserProfile = {
  user_id: number;
  display_currency: string;
};

export type ProfilePatch = {
  display_currency?: string;
};

export function getProfile(): Promise<UserProfile> {
  return authedGet<UserProfile>("/v1/profile");
}

export function patchProfile(body: ProfilePatch): Promise<UserProfile> {
  return authedPatch<UserProfile>("/v1/profile", body);
}
