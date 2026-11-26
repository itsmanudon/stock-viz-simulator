import "server-only";

/**
 * A4.7 (M9.3): drills and decks, `/v1/drills` (authed). While a drill is
 * anonymised every response names the symbol "Stock A" and shifts its dates
 * by whole weeks; the page never calls the `/v1/replay` routes for a drill
 * (they 404 until it is revealed).
 */

import type { Drawing, DrawingsResponse } from "@/lib/drawings/kinds";
import type {
  DrillDeck,
  DrillDeckRequest,
  DrillPlan,
  DrillPlanInput,
  DrillView,
} from "@/lib/drills";

import { toApiPoints } from "./drawings";
import type {
  ReplayDrawingInput,
  ReplayEvents,
  ReplayOrder,
  ReplayOrderInput,
  ReplaySession,
  ReplaySubmit,
} from "./replay";
import { authedDelete, authedGet, authedPatch, authedPost, authedPut } from "./server";
import type { Indicators } from "./types";

export function listDrillDecks(): Promise<DrillDeck[]> {
  return authedGet("/v1/drills/decks");
}

export function getDrillDeck(deckId: number): Promise<DrillDeck> {
  return authedGet(`/v1/drills/decks/${deckId}`);
}

export function createDrillDeck(body: DrillDeckRequest): Promise<DrillDeck> {
  return authedPost("/v1/drills/decks", body);
}

export function deleteDrillDeck(deckId: number): Promise<void> {
  return authedDelete(`/v1/drills/decks/${deckId}`);
}

export function getDrill(drillId: number): Promise<DrillView> {
  return authedGet(`/v1/drills/${drillId}`);
}

export function putDrillPlan(drillId: number, body: DrillPlanInput): Promise<DrillPlan> {
  return authedPut(`/v1/drills/${drillId}/plan`, body);
}

export function submitDrillOrder(drillId: number, body: ReplayOrderInput): Promise<ReplaySubmit> {
  const orderType = body.order_type ?? "market";
  return authedPost(`/v1/drills/${drillId}/orders`, {
    side: body.side,
    order_type: orderType,
    quantity: body.quantity,
    ...(orderType === "market" ? {} : { limit_price: body.limit_price }),
  });
}

export function cancelDrillOrder(drillId: number, orderId: number): Promise<ReplayOrder> {
  return authedPost(`/v1/drills/${drillId}/orders/${orderId}/cancel`);
}

/** `expectedCurrentAt` is the (shown) date on screen: a repeat changes nothing. */
export function advanceDrill(drillId: number, expectedCurrentAt?: string): Promise<ReplaySession> {
  const qs = expectedCurrentAt
    ? `?expected_current_at=${encodeURIComponent(expectedCurrentAt)}`
    : "";
  return authedPost(`/v1/drills/${drillId}/advance${qs}`);
}

export function revealDrill(drillId: number): Promise<DrillView> {
  return authedPost(`/v1/drills/${drillId}/reveal`);
}

export function getDrillIndicators(drillId: number, names: string[]): Promise<Indicators> {
  const q = new URLSearchParams({ names: names.join(",") });
  return authedGet(`/v1/drills/${drillId}/indicators?${q.toString()}`);
}

export function getDrillEvents(drillId: number): Promise<ReplayEvents> {
  return authedGet(`/v1/drills/${drillId}/events`);
}

export function listDrillDrawings(drillId: number): Promise<DrawingsResponse> {
  return authedGet(`/v1/drills/${drillId}/drawings`);
}

export function createDrillDrawing(drillId: number, input: ReplayDrawingInput): Promise<Drawing> {
  return authedPost(`/v1/drills/${drillId}/drawings`, {
    ...input,
    points: toApiPoints(input.points),
  });
}

export function updateDrillDrawing(
  drillId: number,
  id: number,
  changes: Partial<Omit<ReplayDrawingInput, "kind">>,
): Promise<Drawing> {
  const body = changes.points ? { ...changes, points: toApiPoints(changes.points) } : changes;
  return authedPatch(`/v1/drills/${drillId}/drawings/${id}`, body);
}

export function deleteDrillDrawing(drillId: number, id: number): Promise<void> {
  return authedDelete(`/v1/drills/${drillId}/drawings/${id}`);
}
