"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { Position } from "@/lib/api/trading";
import { formatCurrency } from "@/lib/portfolio-view-model";

export type RebalanceLine = {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  amount: number;
};

/**
 * Whole shares to move each holding to its target share of NAV, at today's
 * value per share in the display currency. Pure, so it is tested directly.
 */
export function rebalanceLines(
  positions: Pick<Position, "ticker" | "quantity" | "market_value">[],
  targets: Record<string, number>,
  nav: number,
): RebalanceLine[] {
  const out: RebalanceLine[] = [];
  for (const p of positions) {
    const qty = Number(p.quantity);
    const value = Number(p.market_value);
    if (!(qty > 0) || !(value > 0) || !(nav > 0)) continue;
    const price = value / qty;
    const target = ((targets[p.ticker] ?? (value / nav) * 100) / 100) * nav;
    const shares = Math.trunc((target - value) / price);
    if (shares === 0) continue;
    out.push({
      ticker: p.ticker,
      side: shares > 0 ? "buy" : "sell",
      quantity: Math.abs(shares),
      amount: Math.abs(shares) * price,
    });
  }
  return out;
}

/**
 * Phase 8.6: a preview of the orders that would move each holding to a target
 * weight. Nothing is placed: each line opens the normal ticket, where the
 * review, the limits and the buying-power checks still apply.
 */
export function RebalancePreview({
  positions,
  nav,
  currency,
}: {
  positions: Position[];
  nav: number;
  currency: string;
}) {
  const held = useMemo(() => positions.filter((p) => Number(p.market_value) > 0), [positions]);
  const [targets, setTargets] = useState<Record<string, number>>(() =>
    Object.fromEntries(
      held.map((p) => [p.ticker, Math.round((Number(p.market_value) / nav) * 1000) / 10]),
    ),
  );
  const lines = useMemo(() => rebalanceLines(held, targets, nav), [held, targets, nav]);
  if (held.length === 0 || !(nav > 0)) return null;
  const total = Object.values(targets).reduce((sum, t) => sum + (Number.isFinite(t) ? t : 0), 0);
  const net = lines.reduce((sum, l) => sum + (l.side === "buy" ? -l.amount : l.amount), 0);

  return (
    <section aria-labelledby="rebalance-heading" className="border-t border-border-muted py-5">
      <h3 id="rebalance-heading" className="text-sm font-semibold">
        Rebalance preview
      </h3>
      <p className="mt-1 text-2xs text-text-tertiary">
        Set a target share of the account for each holding. Whole shares at today&apos;s value; the
        rest stays in cash. Nothing is placed: each line opens the ticket.
      </p>
      <div className="mt-3 grid gap-5 lg:grid-cols-2">
        <ul aria-label="Targets" className="space-y-2">
          {held.map((p) => (
            <li key={p.ticker} className="flex items-center justify-between gap-3 text-sm">
              <label htmlFor={`target-${p.ticker}`} className="ticker font-semibold">
                {p.ticker}
              </label>
              <span className="flex items-center gap-1.5">
                <input
                  id={`target-${p.ticker}`}
                  type="number"
                  inputMode="decimal"
                  min={0}
                  max={100}
                  step={0.1}
                  value={targets[p.ticker] ?? 0}
                  onChange={(e) =>
                    setTargets((prev) => ({ ...prev, [p.ticker]: Number(e.target.value) }))
                  }
                  className="h-8 w-20 rounded-md border border-input bg-transparent px-2 text-right font-mono text-sm"
                />
                <span className="text-xs text-text-tertiary">%</span>
              </span>
            </li>
          ))}
          <li className="flex justify-between text-xs text-text-secondary">
            <span>Cash left</span>
            <span className={`font-mono ${total > 100 ? "text-warning" : ""}`}>
              {(100 - total).toFixed(1)}%
            </span>
          </li>
          {total > 100 ? (
            <li className="text-xs text-warning">Targets add up to more than 100%.</li>
          ) : null}
        </ul>
        <div>
          {lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              At these targets no whole share needs to move.
            </p>
          ) : (
            <ul aria-label="Orders to reach the targets" className="space-y-1.5 text-sm">
              {lines.map((line) => (
                <li key={line.ticker} className="flex items-center justify-between gap-3">
                  <span>
                    {line.side === "buy" ? "Buy" : "Sell"} {line.quantity}{" "}
                    <span className="ticker font-semibold">{line.ticker}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="font-mono text-xs text-text-secondary" data-financial>
                      ≈ {formatCurrency(line.amount, currency)}
                    </span>
                    <Link
                      href={`/trade?ticker=${encodeURIComponent(line.ticker)}`}
                      className="text-xs text-brand hover:underline"
                    >
                      Open ticket
                    </Link>
                  </span>
                </li>
              ))}
              <li className="pt-1 text-xs text-text-tertiary">
                Cash {net >= 0 ? "in" : "out"}: {formatCurrency(Math.abs(net), currency)}
              </li>
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
