"use client";

import { useEffect, useState } from "react";

import type { LimitPreview } from "@/lib/api/trading";

/**
 * Phase 8.5: in the order review, what this buy would do to each limit the
 * user has set. Silent when no limits are set or the preview fails; the
 * server checks again when the order is placed, so this is advice only.
 */
export function LimitPreviewRows({ ticker, quantity }: { ticker: string; quantity: string }) {
  const [preview, setPreview] = useState<LimitPreview | null>(null);

  useEffect(() => {
    if (!ticker || !(Number(quantity) > 0)) return;
    const controller = new AbortController();
    const q = new URLSearchParams({ ticker, quantity });
    fetch(`/api/limits-check?${q.toString()}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((body: LimitPreview | null) => setPreview(body))
      .catch(() => setPreview(null));
    return () => controller.abort();
  }, [ticker, quantity]);

  if (!preview || preview.checks.length === 0) return null;
  return (
    <div aria-label="Your limits" className="rounded-xl border border-border-muted bg-card text-xs">
      <p className="px-3 pt-2.5 text-muted-foreground">Your limits after this order</p>
      <ul className="divide-y divide-border-muted">
        {preview.checks.map((check) => (
          <li key={check.limit} className="flex items-start justify-between gap-4 px-3 py-2">
            <span className="capitalize text-muted-foreground">{check.label}</span>
            <span
              className={`text-right font-mono tabular-nums ${check.breached ? "text-warning" : ""}`}
            >
              {check.value_after === null
                ? (check.note ?? "—")
                : `${check.value_after.toFixed(2)}% · limit ${check.cap.toFixed(2)}%`}
            </span>
          </li>
        ))}
      </ul>
      {preview.breached ? (
        <output className="block px-3 pb-2.5 text-warning">
          This order crosses one of your limits, so it will be refused. Change the quantity or your
          limits in Settings.
        </output>
      ) : null}
    </div>
  );
}
