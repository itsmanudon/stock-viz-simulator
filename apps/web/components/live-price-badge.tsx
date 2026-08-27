"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  ticker: string;
  initialPrice: number | null;
  currency: string;
};

type LiveState = "connecting" | "live" | "error";

function fmt(n: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: currency === "JPY" ? 0 : 2,
      maximumFractionDigits: currency === "JPY" ? 0 : 2,
    }).format(n);
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

export function LivePriceBadge({ ticker, initialPrice, currency }: Props) {
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
    <div
      className="inline-flex items-center gap-1.5 text-[11px] text-text-tertiary"
      title="Indicative price simulated from the latest cached close"
    >
      <span>Indicative</span>
      <span className="font-mono tabular-nums">{price !== null ? fmt(price, currency) : "—"}</span>
      <span aria-hidden>·</span>
      <span>{liveState === "error" ? "unavailable" : "simulated"}</span>
      <span className="sr-only">This is not a realtime market quote.</span>
    </div>
  );
}
