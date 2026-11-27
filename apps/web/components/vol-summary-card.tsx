/**
 * Volatility summary (A9.4, M6.3) on the stock page's Options tab: the ATM
 * term structure with 25-delta skew per expiry, VRP (implied minus realised)
 * and IV rank and percentile over the stored snapshots.
 */

import type { VolSummary } from "@/lib/api/option-exposure";

const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`;
const pts = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pts`;

export function VolSummaryCard({ summary }: { summary: VolSummary }) {
  const s = summary;
  return (
    <section aria-labelledby="vol-title" className="space-y-3" data-testid="vol-summary">
      <h3 id="vol-title" className="text-base font-semibold">
        Implied volatility
      </h3>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(
          [
            ["30-day ATM IV", pct(s.atm_30d), "vol-atm"],
            ["21-session realised", pct(s.realised_21d), "vol-rv"],
            ["VRP (implied − realised)", pts(s.vrp), "vol-vrp"],
            [
              "IV rank / percentile",
              s.iv_rank === null || s.iv_rank === undefined
                ? `needs 20 snapshots (${s.snapshots})`
                : `${Math.round(s.iv_rank * 100)} / ${Math.round((s.iv_percentile ?? 0) * 100)}`,
              "vol-rank",
            ],
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
      {s.term.length ? (
        <table className="w-full max-w-md text-xs" data-testid="vol-term">
          <caption className="text-left text-text-tertiary">Term structure</caption>
          <thead>
            <tr className="text-text-tertiary">
              <th className="text-left font-normal">Expiry</th>
              <th className="text-right font-normal">Days</th>
              <th className="text-right font-normal">ATM IV</th>
              <th className="text-right font-normal">25Δ skew</th>
            </tr>
          </thead>
          <tbody>
            {s.term.map((t) => (
              <tr key={t.expiry}>
                <td>{t.expiry}</td>
                <td className="text-right">{t.days}</td>
                <td className="text-right font-mono tabular-nums">{pct(t.atm_iv)}</td>
                <td className="text-right font-mono tabular-nums">{pts(t.skew_25d)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="text-xs text-text-tertiary">{s.method}</p>
    </section>
  );
}
