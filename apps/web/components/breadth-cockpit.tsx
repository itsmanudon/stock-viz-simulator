/**
 * The breadth and diffusion cockpit on /markets (A7.1, M3.3): per market,
 * the latest session's figures and a year of the A/D line, the McClellan
 * oscillator and the share above the 200-day average, from `/v1/breadth`.
 * Every figure counts the stored members with a bar that session; the
 * symbol list is today's (survivorship-biased), as the note says.
 */

import { Sparkline } from "@/components/sparkline";
import type { Breadth, BreadthPoint } from "@/lib/api/breadth";

const MARKET_LABEL = { US: "US", IN: "India" } as const;

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(0)}%`;
}

function series(points: BreadthPoint[], key: keyof BreadthPoint): number[] {
  return points
    .map((p) => p[key])
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
}

function Figure({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div title={title}>
      <dt className="text-[11px] text-text-tertiary">{label}</dt>
      <dd className="font-mono text-sm tabular-nums">{value}</dd>
    </div>
  );
}

function MarketBreadth({ breadth }: { breadth: Breadth }) {
  const points = breadth.points;
  const last = points[points.length - 1];
  const label = MARKET_LABEL[breadth.market];
  if (!last) {
    return <p className="text-sm text-text-secondary">{label}: no stored bars in the last year.</p>;
  }
  const thrustAt = [...points].reverse().find((p) => p.thrust)?.date;
  return (
    <div
      className="space-y-3 rounded-lg border border-border-muted p-4"
      data-testid={`breadth-${breadth.market}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        <span className="text-xs text-text-tertiary">
          {last.date} · {last.members} members
        </span>
      </div>
      <dl className="grid grid-cols-3 gap-3 sm:grid-cols-6">
        <Figure
          label="Advancing"
          value={`${last.advancers} / ${last.advancers + last.decliners}`}
        />
        <Figure
          label="A/D ratio 20d"
          value={
            last.ad_ratio_20 === null || last.ad_ratio_20 === undefined
              ? "—"
              : last.ad_ratio_20.toFixed(2)
          }
          title={breadth.method.ad_ratio}
        />
        <Figure
          label="McClellan"
          value={
            last.mcclellan === null || last.mcclellan === undefined
              ? "—"
              : last.mcclellan.toFixed(1)
          }
          title={breadth.method.mcclellan}
        />
        <Figure
          label="Highs − lows"
          value={String(last.highs_minus_lows)}
          title={breadth.method.new_highs}
        />
        <Figure
          label="Above 50d"
          value={pct(last.pct_above_50)}
          title={breadth.method.pct_above_sma}
        />
        <Figure
          label="Above 200d"
          value={pct(last.pct_above_200)}
          title={breadth.method.pct_above_sma}
        />
      </dl>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {(
          [
            ["A/D line", "ad_line"],
            ["McClellan oscillator", "mcclellan"],
            ["% above 200d", "pct_above_200"],
          ] as const
        ).map(([title, key]) => (
          <div key={key}>
            <p className="text-[11px] text-text-tertiary">{title}</p>
            <Sparkline closes={series(points, key)} width={220} height={40} />
          </div>
        ))}
      </div>
      <p className="text-[11px] text-text-tertiary">
        {thrustAt ? `Last breadth thrust: ${thrustAt}. ` : "No breadth thrust in this window. "}
        RSI ≥ 50: {pct(last.pct_rsi_50)}.
      </p>
    </div>
  );
}

export function BreadthCockpit({ markets }: { markets: Breadth[] }) {
  if (markets.length === 0) return null;
  return (
    <section
      aria-labelledby="breadth-title"
      className="mt-5 space-y-3"
      data-testid="breadth-cockpit"
    >
      <h2 id="breadth-title" className="text-base font-semibold tracking-tight">
        Breadth and diffusion
      </h2>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {markets.map((b) => (
          <MarketBreadth key={b.market} breadth={b} />
        ))}
      </div>
      <p className="text-xs text-text-tertiary">{markets[0]?.universe_note}</p>
    </section>
  );
}
