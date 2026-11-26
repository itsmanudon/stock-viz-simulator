"use client";

/**
 * A4.3 (M7.4): the report card under a backtest result. Net of costs, each
 * metric with its formula one click (or Enter) away; the Monte Carlo
 * drawdown fan; the regime split. Shared by both /backtest modes and the
 * saved-run pages.
 */

import { useEffect, useId, useRef, useState } from "react";

import { FigureStrip } from "@/components/figure-strip";
import { ResearchSectionHeader } from "@/components/research-page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type MonteCarloFan,
  REGIME_LABEL,
  type RegimeSplit,
  type ReportCard as ReportCardData,
  formatMetric,
  pctText,
  signedPct,
} from "@/lib/report-card";

/** A label with an "i" button that shows how the figure is computed. */
export function FormulaTip({
  label,
  formula,
  name,
}: {
  /** Visible text before the button (may be empty). */
  label: string;
  formula: string;
  /** What the formula is for, in the button's spoken name. */
  name?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
        return;
      }
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <span ref={ref} className="inline-flex flex-wrap items-center gap-1">
      {label}
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`How ${name ?? label} is computed`}
        title={formula}
        onClick={() => setOpen((v) => !v)}
        className="inline-grid size-4 place-items-center rounded-full border border-border-muted text-3xs text-text-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-brand"
        data-testid="formula-tip"
      >
        i
      </button>
      {open ? (
        <span
          id={id}
          role="tooltip"
          className="block w-full rounded-md border border-border-muted bg-surface-elevated p-2 font-mono text-2xs leading-4 whitespace-normal text-foreground"
        >
          {formula}
        </span>
      ) : null}
    </span>
  );
}

export function ReportCard({
  report,
  currency,
  unit = "day",
}: {
  report: ReportCardData;
  currency: string;
  /** A6.4: an intraday run's returns are per bar, not per day. */
  unit?: "day" | "bar";
}) {
  const sharpe = report.sharpe;
  return (
    <section aria-labelledby="report-card-heading" data-testid="report-card">
      <ResearchSectionHeader
        id="report-card-heading"
        title="Report card, net of costs"
        description="From the net equity curve and the closed round trips. Select i for each formula."
      />
      <FigureStrip
        label="Report card"
        figures={[
          ...report.metrics.map((m) => ({
            label: m.label,
            value: (
              <span title={m.note ?? undefined} data-metric={m.key}>
                {formatMetric(m, currency)}
              </span>
            ),
            note: <FormulaTip label={m.note ?? ""} name={m.label} formula={m.formula} />,
          })),
          {
            label: "Sharpe (annual)",
            value: sharpe.sharpe_annual.toFixed(2),
            note: (
              <FormulaTip
                label={`${sharpe.observations} ${unit}s`}
                formula={`mean / sample std of daily returns minus ${(sharpe.risk_free_rate * 100).toFixed(0)}%/252, x sqrt(252)`}
              />
            ),
          },
        ]}
      />
      {report.monte_carlo ? (
        <McFan fan={report.monte_carlo} currency={currency} unit={unit} />
      ) : (
        <p className="mt-4 text-xs text-text-tertiary">{report.monte_carlo_reason}</p>
      )}
      <RegimeTable regimes={report.regimes} />
    </section>
  );
}

function money(v: number, currency: string): string {
  return v.toLocaleString("en-US", { style: "currency", currency, maximumFractionDigits: 0 });
}

/** The bootstrap's 5th-95th percentile band and median, as inline SVG. */
export function McFan({
  fan,
  currency,
  unit = "day",
}: {
  fan: MonteCarloFan;
  currency: string;
  unit?: "day" | "bar";
}) {
  const points = fan.fan;
  const W = 640;
  const H = 200;
  const pad = { l: 0, r: 0, t: 6, b: 6 };
  const lo = Math.min(...points.map((p) => p.p5));
  const hi = Math.max(...points.map((p) => p.p95));
  const x = (i: number) => pad.l + (i / Math.max(1, points.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / Math.max(hi - lo, 1e-9)) * (H - pad.t - pad.b);
  const band = [
    ...points.map((p, i) => `${x(i)},${y(p.p95)}`),
    ...points.map((p, i) => `${x(i)},${y(p.p5)}`).reverse(),
  ].join(" ");
  const median = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.p50)}`).join(" ");
  const start = points[0]?.p50 ?? 0;
  return (
    <div className="mt-6 space-y-2" data-testid="mc-fan">
      <h3 className="text-sm font-semibold">Monte Carlo drawdown fan</h3>
      <FigureStrip
        label="Bootstrap drawdowns"
        figures={[
          {
            label: "Max drawdown, median path",
            value: <span className="text-negative">-{pctText(fan.max_drawdown.p50)}</span>,
          },
          {
            label: "Max drawdown, 95th pct",
            value: <span className="text-negative">-{pctText(fan.max_drawdown.p95)}</span>,
            note: "1 path in 20 worse",
          },
          {
            label: "This run's drawdown",
            value: <span className="text-negative">-{pctText(fan.actual_max_drawdown)}</span>,
          },
          { label: "Paths ending below start", value: pctText(fan.prob_loss) },
        ]}
      />
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-48 w-full"
        role="img"
        aria-label={`Bootstrap NAV fan: 5th to 95th percentile from ${money(points.at(-1)?.p5 ?? 0, currency)} to ${money(points.at(-1)?.p95 ?? 0, currency)} at the end, median ${money(points.at(-1)?.p50 ?? 0, currency)}.`}
        preserveAspectRatio="none"
      >
        <line
          x1={pad.l}
          x2={W - pad.r}
          y1={y(start)}
          y2={y(start)}
          stroke="var(--border-muted)"
          strokeDasharray="3 3"
        />
        <polygon points={band} fill="var(--brand)" fillOpacity={0.15} />
        <path d={median} fill="none" stroke="var(--brand)" strokeWidth={1.5} />
      </svg>
      <div className="flex justify-between font-mono text-3xs text-text-tertiary">
        <span>{points[0]?.date}</span>
        <span>
          start {money(start, currency)} (dashed) · top {money(hi, currency)}
        </span>
        <span>{points.at(-1)?.date}</span>
      </div>
      <p className="text-xs leading-5 text-text-tertiary">
        {fan.paths.toLocaleString("en-US")} paths of the run's own{" "}
        {unit === "bar" ? "per-bar" : "daily"} net returns, resampled in blocks of mean length{" "}
        {fan.mean_block} (stationary bootstrap) for {fan.horizon_days}{" "}
        {unit === "bar" ? "bars" : "sessions"}; seed {fan.seed}, so the same run draws the same fan.
        Band: 5th to 95th percentile; line: median. Ends {money(fan.final_nav.p5, currency)} to{" "}
        {money(fan.final_nav.p95, currency)}.
      </p>
    </div>
  );
}

export function RegimeTable({ regimes }: { regimes: RegimeSplit }) {
  const rows = regimes.rows ?? [];
  return (
    <div className="mt-6 space-y-2" data-testid="regime-split">
      <h3 className="text-sm font-semibold">
        By market regime{regimes.index ? ` (${regimes.index})` : ""}
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-text-secondary">{regimes.reason ?? "No sessions."}</p>
      ) : (
        <div className="overflow-x-auto border-y border-border-muted">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Regime</TableHead>
                <TableHead className="text-right">Sessions</TableHead>
                <TableHead className="text-right">Return</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Sharpe</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Exposure</TableHead>
                <TableHead className="hidden text-right md:table-cell">Entries</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.state ?? "unknown"} data-state={r.state ?? "unknown"}>
                  <TableCell>{REGIME_LABEL(r.state)}</TableCell>
                  <TableCell className="text-right font-mono">
                    {r.sessions}
                    <span className="block text-2xs text-text-tertiary">{pctText(r.share)}</span>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {signedPct(r.total_return)}
                    <span className="block text-2xs text-text-tertiary sm:hidden">
                      Sharpe{" "}
                      {r.sharpe === null || r.sharpe === undefined ? "n/a" : r.sharpe.toFixed(2)}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-right font-mono sm:table-cell">
                    {r.sharpe === null || r.sharpe === undefined ? "n/a" : r.sharpe.toFixed(2)}
                  </TableCell>
                  <TableCell className="hidden text-right font-mono sm:table-cell">
                    {pctText(r.exposure)}
                  </TableCell>
                  <TableCell className="hidden text-right font-mono md:table-cell">
                    {r.trades_entered}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <p className="text-xs leading-5 text-text-tertiary">
        {regimes.method}
        {rows.length > 0 && regimes.reason ? ` ${regimes.reason}` : ""}
      </p>
    </div>
  );
}
