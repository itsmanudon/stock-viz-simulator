"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  ticker: string;
  initialPrice: number | null;
};

type LiveState = "connecting" | "live" | "error";

function fmt(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function LivePriceBadge({ ticker, initialPrice }: Props) {
  const [price, setPrice] = useState<number | null>(initialPrice);
  const [liveState, setLiveState] = useState<LiveState>("connecting");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const es = new EventSource(`${apiUrl}/v1/stream/quotes/${ticker}`);
    esRef.current = es;

    es.onopen = () => setLiveState("live");
    es.onmessage = (ev: MessageEvent<string>) => {
      try {
        const data = JSON.parse(ev.data) as { price?: number; error?: string };
        if (data.error !== undefined || data.price === undefined) {
          setLiveState("error");
          es.close();
        } else {
          setPrice(data.price);
          setLiveState("live");
        }
      } catch {
        setLiveState("error");
        es.close();
      }
    };
    es.onerror = () => {
      setLiveState("error");
      es.close();
    };

    return () => {
      es.close();
    };
  }, [ticker]);

  return (
    <div className="flex items-center justify-end gap-2 font-mono">
      <div className="text-3xl">${price !== null ? fmt(price) : "—"}</div>
      {liveState === "live" ? (
        <span className="relative flex h-2 w-2" title="Simulated quote">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
        </span>
      ) : liveState === "error" ? (
        <span className="h-2 w-2 rounded-full bg-yellow-400" title="Simulated quote unavailable" />
      ) : null}
    </div>
  );
}
