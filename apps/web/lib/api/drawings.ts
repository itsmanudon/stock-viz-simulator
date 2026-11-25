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

export function createDrawing(input: DrawingInput): Promise<Drawing> {
  return authedPost<Drawing>("/v1/drawings", input);
}

export type DrawingChanges = {
  points?: DrawingPoint[];
  style?: DrawingStyle;
  label?: string | null;
  locked?: boolean;
};

export function updateDrawing(id: number, changes: DrawingChanges): Promise<Drawing> {
  return authedPatch<Drawing>(`/v1/drawings/${id}`, changes);
}

export function deleteDrawing(id: number): Promise<void> {
  return authedDelete(`/v1/drawings/${id}`);
}
