import "server-only";

import type {
  Drawing,
  DrawingKind,
  DrawingPoint,
  DrawingStyle,
  DrawingsResponse,
} from "@/lib/drawings/kinds";

import { authedDelete, authedGet, authedPatch, authedPost } from "./server";

/** A3.2: the signed-in user's drawings on one symbol (`/v1/drawings`). */
export function listDrawings(ticker: string): Promise<DrawingsResponse> {
  return authedGet<DrawingsResponse>(`/v1/drawings?ticker=${encodeURIComponent(ticker)}`);
}

export type DrawingInput = {
  ticker: string;
  kind: DrawingKind;
  points: DrawingPoint[];
  style?: DrawingStyle;
  label?: string | null;
  locked?: boolean;
};

/** The API's points: an empty price (an anchored VWAP's date-only point) is null. */
export function toApiPoints(points: DrawingPoint[]): { ts: string | null; price: string | null }[] {
  return points.map((p) => ({ ts: p.ts, price: p.price === "" ? null : p.price }));
}

export function createDrawing(input: DrawingInput): Promise<Drawing> {
  return authedPost<Drawing>("/v1/drawings", { ...input, points: toApiPoints(input.points) });
}

export type DrawingChanges = {
  points?: DrawingPoint[];
  style?: DrawingStyle;
  label?: string | null;
  locked?: boolean;
};

export function updateDrawing(id: number, changes: DrawingChanges): Promise<Drawing> {
  const body = changes.points ? { ...changes, points: toApiPoints(changes.points) } : changes;
  return authedPatch<Drawing>(`/v1/drawings/${id}`, body);
}

export function deleteDrawing(id: number): Promise<void> {
  return authedDelete(`/v1/drawings/${id}`);
}
