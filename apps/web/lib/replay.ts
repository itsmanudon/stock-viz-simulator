import type { Bar } from "@/lib/api/types";

export const REPLAY_PROFILE_LABEL = "legacy_close v1";
export const REPLAY_DEFAULT_CASH = "100000";
export const REPLAY_CASH_PRESETS = ["25000", "50000", "100000", "250000"] as const;

export function isoDate(iso: string): string {
  return iso.slice(0, 10);
}

export function toReplayTimestamp(date: string): string {
  return `${date}T00:00:00.000Z`;
}

export function formatReplayDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatReplayShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatReplayDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function replayProgressPct(
  startAt: string,
  currentAt: string,
  endAt: string,
  status: string,
): number {
  if (status === "completed" || currentAt >= endAt) return 100;
  const start = Date.parse(startAt);
  const current = Date.parse(currentAt);
  const end = Date.parse(endAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return Math.max(0, Math.min(100, Math.round(((current - start) / (end - start)) * 100)));
}

export function replayBarsToChart(
  bars: Array<{
    ts: string;
    open: string;
    high: string;
    low: string;
    close: string;
    volume: number;
  }>,
): Bar[] {
  return bars.map((bar) => ({
    ts: bar.ts,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
  }));
}

export function replayStatusLabel(status: string): string {
  if (status === "completed") return "Completed";
  if (status === "cancelled") return "Cancelled";
  return "Active";
}

export function replayErrorMessage(status: number, detail?: string): string {
  if (status === 404) return "That replay session was not found.";
  if (status === 409 && detail?.toLowerCase().includes("locked")) {
    return "Thesis fields are locked after the first fill. You can still update reflection.";
  }
  if (status === 409) return "This replay is no longer active.";
  if (status === 400) return "That historical range has no stored daily bars.";
  if (status === 422) return "Not enough replay cash or shares for that order.";
  if (status === 401) return "Sign in to use Replay Lab.";
  return "Something went wrong with this replay.";
}

export function replayFillMarkers(fills: Array<{ side: string; evaluated_at: string }>): Array<{
  time: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown";
  text: string;
}> {
  return fills.map((fill) =>
    fill.side.toLowerCase() === "buy"
      ? {
          time: fill.evaluated_at,
          position: "belowBar" as const,
          color: "rgb(34 197 94)",
          shape: "arrowUp" as const,
          text: "BUY",
        }
      : {
          time: fill.evaluated_at,
          position: "aboveBar" as const,
          color: "rgb(239 68 68)",
          shape: "arrowDown" as const,
          text: "SELL",
        },
  );
}

export function datesDiffer(requested: string | undefined, resolvedIso: string): boolean {
  if (!requested) return false;
  return isoDate(requested) !== isoDate(resolvedIso);
}
