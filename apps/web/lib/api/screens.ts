import "server-only";

import { authedDelete, authedGet, authedPatch, authedPost } from "./server";

/** A saved screener (Phase 6.2): a name and the screener URL's query string. */
export type SavedScreen = {
  id: number;
  name: string;
  query: string;
  /** A2.2: the setup version the screen runs, if any. */
  setup_version_id?: number | null;
  /** A2.3: a notification when the rule's members change (nightly). */
  notify_on_change?: boolean;
  created_at: string;
  updated_at: string;
};

export function listSavedScreens(): Promise<SavedScreen[]> {
  return authedGet<SavedScreen[]>("/v1/screens");
}

/** Saves, or replaces the query of the screen with the same name. */
export function saveScreen(
  name: string,
  query: string,
  options: { setupVersionId?: number | null; notifyOnChange?: boolean } = {},
): Promise<SavedScreen> {
  return authedPost<SavedScreen>("/v1/screens", {
    name,
    query,
    setup_version_id: options.setupVersionId ?? null,
    ...(options.notifyOnChange === undefined ? {} : { notify_on_change: options.notifyOnChange }),
  });
}

/** A2.3: turn the nightly change notification on or off. */
export function setScreenNotify(id: number, notifyOnChange: boolean): Promise<SavedScreen> {
  return authedPatch<SavedScreen>(`/v1/screens/${id}`, { notify_on_change: notifyOnChange });
}

export function deleteScreen(id: number): Promise<void> {
  return authedDelete(`/v1/screens/${id}`);
}
