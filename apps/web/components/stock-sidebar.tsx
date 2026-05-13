"use client";

import { useState } from "react";

import Link from "next/link";

import type { Symbol } from "@/lib/api/types";

type Props = {
  symbols: Symbol[];
  currentTicker: string;
  /** Preserved on navigation so tf/indicator state isn't lost when switching tickers. */
  tf: string;
  indicators: string;
};

export function StockSidebar({ symbols, currentTicker, tf, indicators }: Props) {
  const [sector, setSector] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const sectors = Array.from(
    new Set(symbols.map((s) => s.sector).filter((s): s is string => Boolean(s))),
  ).sort();

  const filtered = symbols.filter((s) => {
    if (sector && s.sector !== sector) return false;
    if (query) {
      const q = query.toUpperCase();
      return s.ticker.includes(q) || s.name.toUpperCase().includes(q);
    }
    return true;
  });

  function stockHref(ticker: string): string {
    const params = new URLSearchParams();
    if (tf) params.set("tf", tf);
    if (indicators) params.set("indicators", indicators);
    const qs = params.toString();
    return `/stocks/${ticker}${qs ? `?${qs}` : ""}`;
  }

  return (
    <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] w-56 shrink-0 flex-col border-r bg-background lg:flex">
      {/* Search */}
      <div className="border-b p-2">
        <input
          type="text"
          placeholder="Search…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-md border bg-transparent px-2.5 py-1.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Sector filter */}
      <div className="flex flex-wrap gap-1 border-b p-2">
        <button
          onClick={() => setSector(null)}
          className={`rounded-md border px-2 py-0.5 text-xs transition hover:bg-accent ${
            sector === null ? "border-primary text-foreground" : "text-muted-foreground"
          }`}
        >
          All
        </button>
        {sectors.map((s) => (
          <button
            key={s}
            onClick={() => setSector(s)}
            className={`rounded-md border px-2 py-0.5 text-xs transition hover:bg-accent ${
              sector === s ? "border-primary text-foreground" : "text-muted-foreground"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Stock list */}
      <nav className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">No results.</p>
        ) : (
          filtered.map((sym) => {
            const active = sym.ticker === currentTicker;
            return (
              <Link
                key={sym.ticker}
                href={stockHref(sym.ticker)}
                className={`flex items-baseline gap-2 px-3 py-2 text-sm transition hover:bg-accent ${
                  active ? "bg-accent/60" : ""
                }`}
              >
                <span className={`font-mono text-xs font-semibold ${active ? "text-primary" : ""}`}>
                  {sym.ticker}
                </span>
                <span className="truncate text-xs text-muted-foreground">{sym.name}</span>
              </Link>
            );
          })
        )}
      </nav>
    </aside>
  );
}
