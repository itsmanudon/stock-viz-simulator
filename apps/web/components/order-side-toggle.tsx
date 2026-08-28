"use client";

import { cn } from "@/lib/utils";

/**
 * Buy / sell segmented control.
 *
 * Colour is load-bearing here, not decoration: on a trading ticket the side is
 * the one field where a mis-click costs money, so the active side is tinted
 * with the positive/negative tokens rather than the brand accent. The
 * standalone `/trade` ticket previously rendered both sides in identical gold,
 * which made buy and sell indistinguishable at a glance.
 *
 * `aria-pressed` carries the state for assistive tech; the disabled state is
 * for protective orders, which are sell-only in this simulator.
 */
export function OrderSideToggle({
  side,
  onChange,
  disabled = false,
  className,
}: {
  side: "buy" | "sell";
  onChange: (side: "buy" | "sell") => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn("grid grid-cols-2 gap-1 rounded-md bg-surface-secondary p-1", className)}
      aria-label="Order side"
    >
      {(["buy", "sell"] as const).map((value) => {
        const active = side === value;
        return (
          <button
            key={value}
            type="button"
            disabled={disabled}
            aria-pressed={active}
            onClick={() => onChange(value)}
            className={cn(
              "h-9 rounded-sm border text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              active
                ? value === "buy"
                  ? "border-positive/40 bg-positive/10 text-positive"
                  : "border-negative/40 bg-negative/10 text-negative"
                : "border-transparent text-text-secondary hover:bg-surface-hover hover:text-foreground",
            )}
          >
            {value === "buy" ? "Buy" : "Sell"}
          </button>
        );
      })}
    </div>
  );
}
