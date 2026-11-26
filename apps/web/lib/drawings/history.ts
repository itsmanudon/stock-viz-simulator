/**
 * Session undo and redo for drawings (A3.2). Each entry is one saved change:
 * a create, an update (before and after) or a delete. Undoing a delete
 * re-creates the drawing, which gets a new id from the API; `remapId` points
 * every entry at it so later steps still find it. Nothing here is stored:
 * the history ends with the page.
 */

import type { Drawing } from "./kinds";

export type HistoryEntry =
  | { type: "create"; drawing: Drawing }
  | { type: "update"; before: Drawing; after: Drawing }
  | { type: "delete"; drawing: Drawing };

export type History = { past: HistoryEntry[]; future: HistoryEntry[] };

export const EMPTY_HISTORY: History = { past: [], future: [] };
export const HISTORY_LIMIT = 100;

export function record(history: History, entry: HistoryEntry): History {
  return { past: [...history.past, entry].slice(-HISTORY_LIMIT), future: [] };
}

/** The change that undoes an entry. */
export function inverse(entry: HistoryEntry): HistoryEntry {
  if (entry.type === "create") return { type: "delete", drawing: entry.drawing };
  if (entry.type === "delete") return { type: "create", drawing: entry.drawing };
  return { type: "update", before: entry.after, after: entry.before };
}

/** Pop the newest change for undo: the entry, and the history with it moved to `future`. */
export function takeUndo(history: History): { entry: HistoryEntry; next: History } | null {
  const entry = history.past.at(-1);
  if (!entry) return null;
  return { entry, next: { past: history.past.slice(0, -1), future: [...history.future, entry] } };
}

export function takeRedo(history: History): { entry: HistoryEntry; next: History } | null {
  const entry = history.future.at(-1);
  if (!entry) return null;
  return { entry, next: { past: [...history.past, entry], future: history.future.slice(0, -1) } };
}

function remapDrawing(d: Drawing, from: number, to: number): Drawing {
  return d.id === from ? { ...d, id: to } : d;
}

/** After a drawing was re-created under a new id, point every entry at it. */
export function remapId(history: History, from: number, to: number): History {
  const map = (e: HistoryEntry): HistoryEntry =>
    e.type === "update"
      ? { ...e, before: remapDrawing(e.before, from, to), after: remapDrawing(e.after, from, to) }
      : { ...e, drawing: remapDrawing(e.drawing, from, to) };
  return { past: history.past.map(map), future: history.future.map(map) };
}
