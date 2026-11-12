"use client";

/**
 * Settle sweep (motion batch 3, the only animation inside the product app).
 *
 * When an order this browser last saw as pending is now filled, one band of
 * light crosses its status chip, once. Nothing else moves: no glow, no
 * bounce, and with reduced motion the band never plays (globals.css).
 *
 * Fills happen at the nightly settle, not while the page is open, so "just
 * filled" means "filled since this browser last showed it". The last status
 * per order lives in localStorage. The /orders page renders each order twice
 * (table and cards), so every chip compares against one snapshot taken on the
 * first read, and the second copy still plays.
 */

import { type ReactNode, useEffect, useRef } from "react";

const KEY = "stockviz:order-status";

let snapshot: Record<string, string> | null = null;

function readSnapshot(): Record<string, string> {
  if (snapshot) return snapshot;
  try {
    snapshot = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Record<string, string>;
  } catch {
    snapshot = {};
  }
  return snapshot;
}

function remember(id: string, status: string) {
  try {
    const current = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Record<string, string>;
    current[id] = status;
    // Keep the store small: the newest 200 orders are plenty.
    const entries = Object.entries(current).slice(-200);
    window.localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Storage blocked or full: the sweep just never plays.
  }
}

export function SettleSweep({
  orderId,
  status,
  children,
}: {
  orderId: number | string;
  status: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const id = String(orderId);
    const before = readSnapshot()[id];
    if (before === "pending" && status === "filled") ref.current?.setAttribute("data-settled", "");
    remember(id, status);
  }, [orderId, status]);

  return (
    <span ref={ref} className="settle-sweep relative inline-flex overflow-hidden rounded-full">
      {children}
    </span>
  );
}
