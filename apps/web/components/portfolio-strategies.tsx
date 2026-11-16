"use client";

/**
 * Open option strategies on the portfolio (Phase 9.5), each closable as a
 * unit in two steps: every open leg at its model value, one net payment.
 */

import { useActionState, useState } from "react";

import {
  type CloseOptionState,
  closeStrategyFormAction,
} from "@/app/(product)/(authed)/trade/options-actions";
import type { OptionStrategy } from "@/lib/api/options";

const INITIAL: CloseOptionState = { error: null, closed: false };

function usd(value: string | number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    Number(value),
  );
}

export function PortfolioStrategies({ strategies }: { strategies: OptionStrategy[] | null }) {
  const open = (strategies ?? []).filter((s) => s.status === "open");
  if (open.length === 0) return null;
  return (
    <section aria-labelledby="strategies-heading" className="mb-8">
      <h2 id="strategies-heading" className="text-lg font-semibold tracking-tight">
        Strategies
      </h2>
      <ul className="mt-3 divide-y divide-border-muted border-y border-border-muted">
        {open.map((s) => {
          const ticker = s.legs[0]?.ticker ?? "";
          const net = Number(s.net_premium);
          return (
            <li
              key={s.id}
              className="grid gap-2 py-3 text-xs sm:grid-cols-[minmax(0,1fr)_auto]"
              aria-label={`${s.label} on ${ticker}`}
            >
              <div>
                <p className="text-sm font-medium">
                  {s.label} <span className="ticker">{ticker}</span>
                </p>
                <p className="mt-1 text-text-tertiary">
                  {s.legs
                    .map(
                      (leg) =>
                        `${leg.side === "short" ? "Write" : "Buy"} ${leg.strike} ${leg.option_type} ${leg.expiry}`,
                    )
                    .join(" · ")}
                </p>
                <p className="mt-1 text-text-secondary">
                  {net >= 0 ? "Received" : "Paid"} {usd(Math.abs(net))}
                  {Number(s.collateral) > 0 ? ` · ${usd(s.collateral)} held back` : ""}
                  {s.max_loss !== null ? ` · can lose at most ${usd(s.max_loss)}` : ""}
                </p>
              </div>
              <CloseStrategyButton id={s.id} label={`${s.label} on ${ticker}`} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function CloseStrategyButton({ id, label }: { id: number; label: string }) {
  const [confirming, setConfirming] = useState(false);
  const [state, action, pending] = useActionState(closeStrategyFormAction, INITIAL);
  const buttonClass =
    "rounded-md border border-border px-2.5 py-1 text-xs font-medium outline-none transition-colors hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring";
  if (!confirming) {
    return (
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={`Close ${label}`}
          className={buttonClass}
        >
          Close strategy
        </button>
        {state.error ? (
          <p role="alert" className="max-w-56 text-right text-2xs text-negative">
            {state.error}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <form
      action={(formData) => {
        setConfirming(false);
        action(formData);
      }}
      className="flex flex-col items-end gap-1"
    >
      <input type="hidden" name="strategy_id" value={id} />
      <p className="text-2xs text-muted-foreground">
        Close every leg at its model value, as one payment?
      </p>
      <div className="flex gap-1.5">
        <button type="button" onClick={() => setConfirming(false)} className={buttonClass}>
          Keep
        </button>
        <button
          type="submit"
          disabled={pending}
          aria-label={`Confirm closing ${label}`}
          className={buttonClass}
        >
          Confirm close
        </button>
      </div>
    </form>
  );
}
