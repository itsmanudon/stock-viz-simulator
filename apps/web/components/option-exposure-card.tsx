/**
 * Gamma and delta exposure (A7.9, M6.2) on the stock page's Options tab:
 * the key levels and a per-strike GEX bar strip from `/v1/options/{t}/exposure`.
 * Volatility-regime context, not direction (the API's note says so).
 */

import type { OptionExposure } from "@/lib/api/option-exposure";
import { cn } from "@/lib/utils";

const money = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : Intl.NumberFormat("en", { notation: "compact", style: "currency", currency: "USD" }).format(
        v,
      );
const price = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toFixed(2);

export function OptionExposureCard({ exposure }: { exposure: OptionExposure }) {
  const e = exposure;
  const near = e.spot
    ? e.strikes.filter((s) => Math.abs(s.strike - (e.spot ?? 0)) <= (e.spot ?? 0) * 0.25)
    : e.strikes;
  const most = Math.max(1, ...near.map((s) => Math.abs(s.gex)));
  return (
    <section aria-labelledby="exposure-title" className="space-y-4" data-testid="option-exposure">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="exposure-title" className="text-base font-semibold">
          Gamma and delta exposure
        </h3>
        <span className="text-xs text-text-tertiary">
          Chain of {e.snapshot_date} · spot {price(e.spot)} · {e.used} contracts
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(
          [
            ["Total GEX (per 1%)", money(e.total_gex), "exposure-gex"],
            ["Gamma flip", price(e.gamma_flip), "exposure-flip"],
            [
              "Call wall / put wall",
              `${price(e.call_wall)} / ${price(e.put_wall)}`,
              "exposure-walls",
            ],
            ["1-day expected move", `±${price(e.expected_move_1d)}`, "exposure-move"],
          ] as const
        ).map(([label, value, id]) => (
          <div key={id}>
            <dt className="text-xs text-text-tertiary">{label}</dt>
            <dd className="font-mono text-sm tabular-nums" data-testid={id}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <div>
        <p className="text-xs text-text-tertiary">GEX by strike, within 25% of spot</p>
        <ul className="mt-1 space-y-0.5" aria-label="GEX by strike">
          {near.map((s) => (
            <li key={s.strike} className="flex items-center gap-2 text-xs">
              <span className="w-14 text-right font-mono tabular-nums text-text-secondary">
                {s.strike}
              </span>
              <span className="relative h-2 flex-1">
                <span
                  className={cn(
                    "absolute top-0 h-2 rounded-sm",
                    s.gex >= 0 ? "left-1/2 bg-positive" : "right-1/2 bg-negative",
                  )}
                  style={{ width: `${(Math.abs(s.gex) / most) * 50}%` }}
                />
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-text-tertiary">{e.note}</p>
    </section>
  );
}
