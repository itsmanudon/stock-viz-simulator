/**
 * A7.14 (M6.1, M6.3): India index options from the owner's local files.
 * Server-renderable. Per underlying: ATM IV with its rank and percentile,
 * put-call skew, PCR by OI, the latest smile by strike offset, and 3 neutral
 * sparklines. Empty when the files were not loaded (production never has them).
 */

import { MethodText } from "@/components/method-text";
import { Sparkline } from "@/components/sparkline";
import type { FoIndia, FoUnderlying } from "@/lib/api/fo";

function n(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : value.toFixed(digits);
}

function lastOf(u: FoUnderlying) {
  return u.days[u.days.length - 1];
}

export function FoUnderlyingCard({ u, skewOffset }: { u: FoUnderlying; skewOffset: number }) {
  const last = lastOf(u);
  const series = (pick: (d: FoUnderlying["days"][number]) => number | null | undefined) =>
    u.days.map(pick).filter((v): v is number => v != null);
  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-card p-4"
      data-testid="fo-underlying"
      data-underlying={u.underlying}
    >
      <div>
        <h2 className="text-base font-semibold">
          {u.underlying}{" "}
          <span className="text-xs font-normal text-text-tertiary">{u.series} series</span>
        </h2>
        <p className="text-2xs text-text-tertiary">
          {u.sessions} sessions, {u.first} to {u.last}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
        {(
          [
            ["ATM IV", n(u.iv_now)],
            ["IV Rank", u.iv_rank == null ? "—" : n(u.iv_rank, 0)],
            ["IV Percentile", u.iv_percentile == null ? "—" : `${n(u.iv_percentile, 0)}%`],
            [`Skew (ATM-${skewOffset} Put − ATM+${skewOffset} Call)`, n(last?.skew)],
            ["PCR (Open Interest)", n(last?.pcr)],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt className="text-2xs text-text-tertiary">{label}</dt>
            <dd className="font-mono tabular-nums" data-testid="fo-figure">
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="grid gap-3 sm:grid-cols-3">
        {(
          [
            ["ATM IV", series((d) => d.atm_iv)],
            ["Skew", series((d) => d.skew)],
            ["PCR", series((d) => d.pcr)],
          ] as const
        ).map(([label, values]) => (
          <div key={label}>
            <p className="text-2xs text-text-tertiary">{label}</p>
            <Sparkline
              closes={values}
              width={220}
              height={40}
              tone="neutral"
              subject={label}
              periodLabel="stored-window"
              className="w-full"
            />
          </div>
        ))}
      </div>
      <table className="w-full text-xs" data-testid="fo-smile">
        <caption className="text-left text-2xs text-text-tertiary">
          IV by strike offset on {u.last}
        </caption>
        <thead className="text-2xs text-text-tertiary">
          <tr>
            <th className="py-1 text-left font-medium">Offset</th>
            <th className="py-1 text-right font-medium">Call IV</th>
            <th className="py-1 text-right font-medium">Put IV</th>
          </tr>
        </thead>
        <tbody>
          {u.smile.map((s) => (
            <tr key={s.offset} className="border-t border-border">
              <td className="py-1">
                {s.offset === 0 ? "ATM" : `ATM${s.offset > 0 ? "+" : ""}${s.offset}`}
              </td>
              <td className="py-1 text-right font-mono tabular-nums">{n(s.call_iv)}</td>
              <td className="py-1 text-right font-mono tabular-nums">{n(s.put_iv)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function FoIndiaView({ data }: { data: FoIndia }) {
  return (
    <div className="space-y-6" data-testid="fo-india">
      {data.underlyings.length === 0 ? (
        <p className="text-sm text-text-secondary" data-testid="fo-empty">
          No India option summaries are stored here. They come from the owner&apos;s files, loaded
          into a local database only (`stockviz.cli fo-load`).
        </p>
      ) : (
        data.underlyings.map((u) => (
          <FoUnderlyingCard
            key={`${u.underlying}-${u.series}`}
            u={u}
            skewOffset={data.skew_offset}
          />
        ))
      )}
      <p className="text-2xs text-text-tertiary">{data.source_note}</p>
      <MethodText note={data.method} />
    </div>
  );
}
