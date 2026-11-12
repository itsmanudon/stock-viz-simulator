import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";

/** A saved screener (Phase 6.2): a name and the screener URL's query string. */
export type SavedScreen = {
  id: number;
  name: string;
  query: string;
  created_at: string;
  updated_at: string;
};

export function listSavedScreens(): Promise<SavedScreen[]> {
  return authedGet<SavedScreen[]>("/v1/screens");
}

/** Saves, or replaces the query of the screen with the same name. */
export function saveScreen(name: string, query: string): Promise<SavedScreen> {
  return authedPost<SavedScreen>("/v1/screens", { name, query });
}

export function deleteScreen(id: number): Promise<void> {
  return authedDelete(`/v1/screens/${id}`);
}
