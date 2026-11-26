"use client";

/**
 * A6.5: an intraday chart's bars kept current from the stream worker's
 * server-sent events (`lib/live-bars.ts` merges them). Opens one
 * `EventSource` per chart while `ticker` is set; the browser reconnects on
 * its own after a drop. New server bars (a reload, another interval) reset
 * the merged state.
 */

import { useEffect, useState } from "react";

import { BROWSER_BASE } from "@/lib/api/client";
import type { Bar } from "@/lib/api/types";
import { type LiveStatus, liveStreamUrl, mergeLiveBar, parseLiveBar } from "@/lib/live-bars";

export type LiveBars = {
  bars: Bar[];
  status: LiveStatus | null;
  lastAt: string | null;
  replayed: boolean;
};

export function useLiveBars(
  ticker: string | null | undefined,
  bars: Bar[],
  interval: string,
  timeZone: string,
): LiveBars {
  const [state, setState] = useState<{ source: Bar[]; bars: Bar[] }>({ source: bars, bars });
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [lastAt, setLastAt] = useState<string | null>(null);
  const [replayed, setReplayed] = useState(false);

  // New server bars replace whatever was merged into the old ones.
  const current = state.source === bars ? state.bars : bars;
  if (state.source !== bars) setState({ source: bars, bars });

  useEffect(() => {
    if (!ticker || typeof EventSource === "undefined") {
      setStatus(null);
      return;
    }
    setStatus("connecting");
    const source = new EventSource(liveStreamUrl(BROWSER_BASE, ticker));
    const onOpen = () => setStatus((s) => (s === "live" ? s : "waiting"));
    const onError = () => setStatus("offline");
    const onBar = (message: MessageEvent<string>) => {
      const event = parseLiveBar(message.data);
      if (!event || event.ticker !== ticker.toUpperCase()) return;
      setState((prev) => {
        const next = mergeLiveBar(prev.bars, event, interval, timeZone);
        return next === prev.bars ? prev : { source: prev.source, bars: next };
      });
      setStatus("live");
      setLastAt(event.closed_at);
      setReplayed(event.replayed);
    };
    source.addEventListener("open", onOpen);
    source.addEventListener("error", onError);
    source.addEventListener("bar", onBar as EventListener);
    return () => {
      source.removeEventListener("open", onOpen);
      source.removeEventListener("error", onError);
      source.removeEventListener("bar", onBar as EventListener);
      source.close();
    };
  }, [ticker, interval, timeZone]);

  return { bars: ticker ? current : bars, status: ticker ? status : null, lastAt, replayed };
}
