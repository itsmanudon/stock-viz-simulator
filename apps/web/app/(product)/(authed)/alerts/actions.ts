"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import {
  type AlertInput,
  createAlert,
  deleteAlert,
  dismissAlert,
  rearmAlert,
  setAlertPaused,
} from "@/lib/api/alerts";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";

const positive = (label: string) =>
  z
    .string()
    .min(1, `${label} is required`)
    .refine((v) => Number(v) > 0 && Number.isFinite(Number(v)), `${label} must be positive`);

const ticker = z
  .string()
  .min(1, "Pick a symbol")
  .max(16)
  .transform((s) => s.trim().toUpperCase());

const repeat = z.enum(["once", "every_cross"]).catch("once");

/** One schema per form kind; each maps to the API's rule body (Phase 7.3). */
const CreateSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("price"),
    ticker,
    direction: z.enum(["above", "below"]),
    target_price: positive("Target price"),
    repeat,
  }),
  z.object({ kind: z.literal("move"), ticker, move_pct: positive("Move size"), repeat }),
  z.object({
    kind: z.literal("technical"),
    ticker,
    indicator: z.string().min(1, "Pick an indicator"),
    op: z.enum(["above", "below"]),
    compare_to: z.string().optional(),
    value: z.string().optional(),
    repeat,
  }),
  z.object({
    kind: z.literal("news"),
    ticker,
    sentiment: z.string().optional(),
    event_type: z.string().max(128).optional(),
    repeat,
  }),
  z.object({
    kind: z.literal("portfolio"),
    metric: z.enum(["drawdown_pct", "position_weight_pct", "day_change_pct"]),
    threshold: positive("Threshold"),
    repeat,
  }),
]);

export type CreateAlertState = {
  error?: string;
  createdId?: number;
};

function apiErrorDetail(err: AuthedApiError): string {
  try {
    const parsed = JSON.parse(err.detail) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // fall through
  }
  return err.detail || `API ${err.status}`;
}

function field(formData: FormData, name: string): string | undefined {
  const value = formData.get(name);
  return typeof value === "string" && value.trim() !== "" ? value.trim() : undefined;
}

function toInput(data: z.infer<typeof CreateSchema>): AlertInput | string {
  switch (data.kind) {
    case "price":
      return {
        ticker: data.ticker,
        direction: data.direction,
        target_price: data.target_price,
        repeat: data.repeat,
      };
    case "move":
      return {
        ticker: data.ticker,
        kind: "price",
        params: { move_pct: Number(data.move_pct) },
        repeat: data.repeat,
      };
    case "technical": {
      const params: Record<string, unknown> = { indicator: data.indicator, op: data.op };
      if (data.compare_to) params.compare_to = data.compare_to;
      else if (data.value !== undefined && Number.isFinite(Number(data.value)))
        params.value = Number(data.value);
      else return "Give a number or a series to compare with";
      return { ticker: data.ticker, kind: "technical", params, repeat: data.repeat };
    }
    case "news":
      return {
        ticker: data.ticker,
        kind: "news",
        params: { sentiment: data.sentiment || null, event_type: data.event_type || null },
        repeat: data.repeat,
      };
    case "portfolio":
      return {
        kind: "portfolio",
        params: { metric: data.metric, threshold: Number(data.threshold) },
        repeat: data.repeat,
      };
  }
}

export async function createAlertAction(
  _prev: CreateAlertState,
  formData: FormData,
): Promise<CreateAlertState> {
  const names = [
    "kind",
    "ticker",
    "direction",
    "target_price",
    "move_pct",
    "indicator",
    "op",
    "compare_to",
    "value",
    "sentiment",
    "event_type",
    "metric",
    "threshold",
    "repeat",
  ];
  const raw = Object.fromEntries(names.map((n) => [n, field(formData, n)]));
  raw.kind = raw.kind ?? "price";
  const parsed = CreateSchema.safeParse(raw);
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }
  const input = toInput(parsed.data);
  if (typeof input === "string") return { error: input };

  try {
    const alert = await createAlert(input);
    if (alert.ticker) revalidatePath(`/stocks/${alert.ticker}`);
    revalidatePath("/alerts");
    revalidatePath("/watchlist");
    return { createdId: alert.id };
  } catch (err) {
    if (err instanceof UnauthenticatedError) return { error: "Sign in to set alerts" };
    if (err instanceof AuthedApiError) return { error: apiErrorDetail(err) };
    throw err;
  }
}

async function onAlert(formData: FormData, run: (id: number) => Promise<unknown>): Promise<void> {
  const idRaw = formData.get("id");
  const id = typeof idRaw === "string" ? Number(idRaw) : Number.NaN;
  if (!Number.isFinite(id)) return;
  try {
    await run(id);
  } catch (err) {
    if (err instanceof AuthedApiError && (err.status === 404 || err.status === 422)) {
      // already gone or nothing to do
    } else if (err instanceof UnauthenticatedError) {
      return;
    } else {
      throw err;
    }
  }
  revalidatePath("/");
  revalidatePath("/alerts");
}

export async function deleteAlertAction(formData: FormData): Promise<void> {
  await onAlert(formData, deleteAlert);
}

export async function dismissAlertAction(formData: FormData): Promise<void> {
  await onAlert(formData, dismissAlert);
}

export async function rearmAlertAction(formData: FormData): Promise<void> {
  await onAlert(formData, rearmAlert);
}

export async function toggleAlertPausedAction(formData: FormData): Promise<void> {
  const paused = formData.get("paused") === "true";
  await onAlert(formData, (id) => setAlertPaused(id, paused));
}
