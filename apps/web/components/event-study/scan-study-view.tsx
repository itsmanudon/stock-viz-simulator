/**
 * A4.5: a scan event study's result. Per horizon: the sample, net and
 * excess returns (mean, median), hit rates, both t-statistics, the
 * distribution (percentiles and a histogram of net returns); counts only
 * under the minimum. Then the events (newest first, linked to the stock
 * page), the method, the universe stamp and "association, not cause".
 * Server-renderable: no state.
 */

import Link from "next/link";

import { UniverseNote } from "@/components/universe-note";
import { type ScanHorizon, type ScanStudy, sharePct, signedPct, tStat } from "@/lib/event-study";
import { formatCloseDate } from "@/lib/stock-workspace";

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value > 0 ? "text-positive" : value < 0 ? "text-negative" : "";
}

function Histogram({ h }: { h: ScanHorizon }) {
  const hist = h.histogram;
  if (!hist || !hist.counts.length) return null;
  const max = Math.max(...hist.counts, 1);
  const w = 240;
  const height = 64;
  const bar = w / hist.counts.length;
  const lo = hist.edges[0];
  const hi = hist.edges[hist.edges.length - 1];
  const zero = lo < 0 && hi > 0 ? ((0 - lo) / (hi - lo)) * w : null;
  return (
    <figure className="mt-2">
      <svg
        viewBox={`0 0 ${w} ${height + 12}`}
        className="h-20 w-full"
        role="img"
        aria-label={`Net ${h.horizon}-session returns from ${signedPct(lo, 1)} to ${signedPct(hi, 1)}: ${hist.counts.join(", ")} events per bin`}
      >
        {hist.counts.map((c, i) => {
          const barH = (c / max) * height;
          const mid = (hist.edges[i] + hist.edges[i + 1]) / 2;
          return (
            <rect
              // biome-ignore lint/suspicious/noArrayIndexKey: bins are positional
              key={i}
              x={i * bar + 0.5}
              y={height - barH}
              width={Math.max(bar - 1, 1)}
              height={barH}
              className={mid >= 0 ? "fill-positive/70" : "fill-negative/70"}
            />
          );
        })}
        {zero !== null ? (
          <line x1={zero} x2={zero} y1={0} y2={height} className="stroke-foreground/50" />
        ) : null}
        <text x={0} y={height + 11} className="fill-text-tertiary" fontSize={9}>
          {signedPct(lo, 1)}
        </text>
        <text x={w} y={height + 11} textAnchor="end" className="fill-text-tertiary" fontSize={9}>
          {signedPct(hi, 1)}
        </text>
      </svg>
      <figcaption className="text-2xs text-text-tertiary">
        Net returns, 1st to 99th percentile (outliers in the end bins).
      </figcaption>
    </figure>
  );
}

function HorizonCard({ h, minEvents }: { h: ScanHorizon; minEvents: number }) {
  const p = h.net_percentiles;
  return (
    <section
      className="rounded-md border border-border-muted bg-card p-4"
      data-testid="scan-horizon"
      data-horizon={h.horizon}
      data-enough={h.enough ? "true" : "false"}
      aria-label={`${h.horizon} sessions after`}
    >
      <h3 className="text-sm font-semibold">{h.horizon} sessions after</h3>
      <p className="mt-0.5 text-xs text-text-tertiary">
        n = <span className="font-mono">{h.n}</span> on {h.symbols} symbols
        {h.incomplete ? ` · ${h.incomplete} without the full window` : ""}
        {h.overlapping ? ` · ${h.overlapping} overlap the previous on their symbol` : ""}
      </p>
      {!h.enough ? (
        <p className="mt-3 text-sm text-text-secondary" data-testid="scan-too-few">
          Too few events to measure: {h.n} of the {minEvents} needed. Counts only.
        </p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <dt className="text-text-tertiary">Mean net return</dt>
              <dd className={`font-mono text-base ${tone(h.mean_net)}`}>{signedPct(h.mean_net)}</dd>
              <dd className="text-2xs text-text-tertiary">median {signedPct(h.median_net)}</dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Excess over base rate</dt>
              <dd className={`font-mono text-base ${tone(h.mean_excess)}`}>
                {signedPct(h.mean_excess)}
              </dd>
              <dd className="text-2xs text-text-tertiary">
                median {signedPct(h.median_excess)} · base {signedPct(h.base_rate)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Hit rate</dt>
              <dd className="font-mono">{sharePct(h.hit_rate)}</dd>
              <dd className="text-2xs text-text-tertiary">
                beat the base {sharePct(h.hit_rate_excess)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">t-statistic (excess)</dt>
              <dd className="font-mono">{tStat(h.t_stat)}</dd>
              <dd className="text-2xs text-text-tertiary">
                clustered by date {tStat(h.t_stat_clustered)} ({h.clusters} dates)
              </dd>
            </div>
          </dl>
          {p ? (
            <p className="mt-3 font-mono text-2xs text-text-secondary">
              5th {signedPct(p.p5, 1)} · 25th {signedPct(p.p25, 1)} · median {signedPct(p.p50, 1)} ·
              75th {signedPct(p.p75, 1)} · 95th {signedPct(p.p95, 1)}
            </p>
          ) : null}
          <Histogram h={h} />
        </>
      )}
    </section>
  );
}

export function ScanStudyView({ study }: { study: ScanStudy }) {
  const horizons = study.horizons;
  const keys = horizons.map((h) => String(h.horizon));
  return (
    <div className="space-y-6" data-testid="scan-study">
      <div className="space-y-1 text-sm">
        <p>
          <span className="text-text-tertiary">Trigger:</span>{" "}
          <span className="font-mono">{study.trigger.canonical}</span>
          {study.trigger.setup_version_id ? (
            <span className="text-text-tertiary">
              {" "}
              · setup version {study.trigger.setup_version_id}
            </span>
          ) : null}
        </p>
        <p className="text-xs text-text-tertiary" data-testid="scan-sample">
          {study.events_found} events on {study.source.name ?? `${study.source.tickers} symbols`} (
          {study.source.tickers} symbols) from {formatCloseDate(study.from)} to{" "}
          {formatCloseDate(study.to)}
          {study.cooldown ? `; cooldown ${study.cooldown} sessions` : ""}
          {study.events_skipped_cooldown ? ` (${study.events_skipped_cooldown} skipped by it)` : ""}
          . Returns are net of a round trip at the venue&apos;s dated fees.
        </p>
      </div>
      <p
        className="rounded-md border border-border-muted px-3 py-2 text-xs text-text-secondary"
        data-testid="scan-disclaimer"
      >
        {study.disclaimer}
      </p>

      <div className="grid gap-4 md:grid-cols-3">
        {horizons.map((h) => (
          <HorizonCard key={h.horizon} h={h} minEvents={study.min_events} />
        ))}
      </div>

      <details className="text-xs leading-5 text-text-tertiary">
        <summary className="cursor-pointer hover:text-foreground">How this was measured</summary>
        <dl className="mt-2 space-y-1.5">
          {Object.entries(study.method).map(([k, v]) => (
            <div key={k}>
              <dt className="inline font-medium text-text-secondary">{k.replace("_", " ")}: </dt>
              <dd className="inline">{v}</dd>
            </div>
          ))}
        </dl>
      </details>
      <UniverseNote universe={study.universe} />

      <section aria-labelledby="scan-events-heading">
        <h3 id="scan-events-heading" className="text-sm font-semibold">
          Events{" "}
          <span className="font-normal text-text-tertiary">
            ({study.events_shown} newest of {study.events_found})
          </span>
        </h3>
        {study.events.length ? (
          <div className="mt-2 overflow-x-auto rounded-md border border-border-muted">
            <table className="w-full text-xs" data-testid="scan-events">
              <thead className="text-text-tertiary">
                <tr className="border-b border-border-muted">
                  <th className="px-3 py-2 text-left font-medium">Symbol</th>
                  <th className="px-3 py-2 text-left font-medium">Date</th>
                  {keys.map((k) => (
                    <th key={k} className="px-3 py-2 text-right font-medium">
                      {k}d net
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {study.events.map((e) => (
                  <tr key={`${e.ticker}-${e.date}`} className="border-b border-border-muted/60">
                    <td className="px-3 py-1.5">
                      <Link
                        href={`/stocks/${encodeURIComponent(e.ticker)}`}
                        className="ticker font-semibold hover:underline"
                      >
                        {e.ticker}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5">{formatCloseDate(e.date)}</td>
                    {keys.map((k) => (
                      <td key={k} className={`px-3 py-1.5 text-right font-mono ${tone(e.net[k])}`}>
                        {signedPct(e.net[k], 1)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-2 text-sm text-text-secondary">
            The trigger never turned true in this window.
          </p>
        )}
      </section>
    </div>
  );
}
