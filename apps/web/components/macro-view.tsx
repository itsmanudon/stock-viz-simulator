/**
 * A9.7 (M1.10, M3.5): the macro board. Server-renderable: one card per FRED
 * series in its group, then the spreads. Colours stay neutral: a rising
 * yield or CPI is not a gain, so nothing here is green or red.
 */

import { Sparkline } from "@/components/sparkline";
import type { MacroOverview, MacroPoint, MacroSeries, MacroSpread } from "@/lib/api/macro";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-24" -> "Nov 24, 2026", read as a calendar date (no time zone shift). */
export function macroDate(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return `${MONTHS[(m ?? 1) - 1]} ${d}, ${y}`;
}

export function isPercentUnits(units: string | null | undefined): boolean {
  return /^percent/i.test(units ?? "") || /percentage points/i.test(units ?? "");
}

export function formatMacroValue(value: number, units: string | null | undefined): string {
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 10 ? 2 : 3;
  const text = value.toLocaleString("en-US", {
    minimumFractionDigits: Math.min(digits, 2),
    maximumFractionDigits: digits,
  });
  return isPercentUnits(units) ? `${text}%` : text;
}

/** A change in points for percent series, else a percent change of the level. */
export function formatMacroChange(
  change: number | null | undefined,
  latest: number | null | undefined,
  units: string | null | undefined,
): string {
  if (change == null || latest == null) return "—";
  const sign = (n: number) => (n > 0 ? "+" : n < 0 ? "−" : "");
  if (isPercentUnits(units)) return `${sign(change)}${Math.abs(change).toFixed(2)} pts`;
  const before = latest - change;
  if (before === 0) return "—";
  const pct = (change / Math.abs(before)) * 100;
  return `${sign(pct)}${Math.abs(pct).toFixed(1)}%`;
}

function SeriesCard({ s }: { s: MacroSeries }) {
  const latest = s.latest ?? null;
  return (
    <li
      className="rounded-lg border border-border bg-card p-3"
      data-testid="macro-series"
      data-series={s.series_id}
      data-stale={s.stale ? "true" : "false"}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{s.label}</p>
          <p className="text-2xs text-text-tertiary">
            <a
              href={s.source_url}
              className="underline-offset-2 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              {s.series_id}
            </a>
            {s.frequency ? ` · ${s.frequency}` : null}
            {s.third_party ? " · Third Party" : null}
          </p>
        </div>
        {latest ? (
          <p className="font-mono text-base tabular-nums" data-testid="macro-value">
            {formatMacroValue(latest.value, s.units)}
          </p>
        ) : null}
      </div>
      {latest ? (
        <>
          <p className="mt-1 text-2xs text-text-tertiary">
            {s.units ? `${s.units} · ` : null}
            {macroDate(latest.day)}
            {s.stale ? <span className="text-warning"> · Not Updated Recently</span> : null}
          </p>
          <dl className="mt-2 flex gap-4 text-xs">
            <div>
              <dt className="text-text-tertiary">1 Month</dt>
              <dd className="font-mono tabular-nums">
                {formatMacroChange(s.change_month, latest.value, s.units)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">1 Year</dt>
              <dd className="font-mono tabular-nums">
                {formatMacroChange(s.change_year, latest.value, s.units)}
              </dd>
            </div>
          </dl>
          <Sparkline
            closes={s.spark.map((p) => p.value)}
            width={240}
            height={36}
            tone="neutral"
            subject={s.label}
            periodLabel="3-year"
            className="mt-2 w-full"
          />
        </>
      ) : (
        <p className="mt-2 text-xs text-text-secondary">
          {s.fetched ? "No values stored yet." : "Not fetched yet."}
        </p>
      )}
    </li>
  );
}

function pointText(p: MacroPoint | null | undefined, units: string): string {
  if (!p) return "—";
  const unit = units === "percentage points" ? " pts" : "";
  return `${p.value.toFixed(2)}${unit} (${macroDate(p.day)})`;
}

function SpreadCard({ sp }: { sp: MacroSpread }) {
  return (
    <li
      className="rounded-lg border border-border bg-card p-3"
      data-testid="macro-spread"
      data-spread={sp.key}
    >
      <p className="text-sm font-medium">{sp.label}</p>
      <p className="text-2xs text-text-tertiary">
        {sp.a} − {sp.b} · {sp.units}
      </p>
      {sp.reason ? (
        <p className="mt-2 text-xs text-text-secondary">{sp.reason}</p>
      ) : (
        <>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-text-tertiary">Now</dt>
              <dd className="font-mono tabular-nums" data-testid="macro-spread-now">
                {pointText(sp.latest, sp.units)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">A Year Earlier</dt>
              <dd className="font-mono tabular-nums">{pointText(sp.year_ago, sp.units)}</dd>
            </div>
          </dl>
          <Sparkline
            closes={sp.points.map((p) => p.value)}
            baseline={0}
            width={240}
            height={36}
            tone="neutral"
            subject={sp.label}
            periodLabel="3-year"
            className="mt-2 w-full"
          />
        </>
      )}
      <p className="mt-2 text-2xs text-text-tertiary">{sp.note}</p>
    </li>
  );
}

export function MacroView({ overview }: { overview: MacroOverview }) {
  const anyFetched = overview.series.some((s) => s.fetched);
  return (
    <div className="space-y-8" data-testid="macro-view">
      {!anyFetched ? (
        <p className="text-sm text-text-secondary" data-testid="macro-empty">
          No macro series are stored yet. They arrive with the weekly FRED fetch (`stockviz.cli
          macro-sync`).
        </p>
      ) : null}
      <section aria-labelledby="macro-spreads" className="space-y-3">
        <h2 id="macro-spreads" className="text-base font-semibold">
          Spreads
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {overview.spreads.map((sp) => (
            <SpreadCard key={sp.key} sp={sp} />
          ))}
        </ul>
      </section>
      {overview.groups.map((group) => {
        const rows = overview.series.filter((s) => s.group === group);
        if (rows.length === 0) return null;
        const id = `macro-${group.toLowerCase().replace(/[^a-z]+/g, "-")}`;
        return (
          <section key={group} aria-labelledby={id} className="space-y-3">
            <h2 id={id} className="text-base font-semibold">
              {group}
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {rows.map((s) => (
                <SeriesCard key={s.series_id} s={s} />
              ))}
            </ul>
          </section>
        );
      })}
      <footer className="space-y-1 text-2xs text-text-tertiary">
        <p>
          Source: {overview.source}.
          {overview.last_fetched_at
            ? ` Last fetched ${macroDate(overview.last_fetched_at.slice(0, 10))}.`
            : null}
        </p>
        <p>{overview.method}</p>
        <p>{overview.third_party_note}</p>
      </footer>
    </div>
  );
}
