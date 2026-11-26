"use client";

/**
 * A4.3: a sweep's overfitting checks on its saved-run page. The probability
 * of backtest overfitting (CSCV) with its logit histogram, and the
 * parameter-plateau heatmap over the two template parameters (net Sharpe by
 * default, or net return), warning when the best setting is an isolated peak.
 */

import { useState } from "react";

import { FigureStrip } from "@/components/figure-strip";
import {
  PARAM_LABEL,
  type PboResult,
  type Plateau,
  formatPlateauValue,
  heatShare,
  pctText,
} from "@/lib/report-card";

export function PboPanel({ pbo, reason }: { pbo?: PboResult | null; reason?: string | null }) {
  if (!pbo) {
    return <p className="text-sm text-text-secondary">{reason ?? "PBO was not computed."}</p>;
  }
  const most = Math.max(1, ...pbo.histogram.map((b) => b.count));
  return (
    <section className="space-y-2" aria-labelledby="pbo-heading" data-testid="pbo-panel">
      <h2 id="pbo-heading" className="text-sm font-semibold">
        Probability of backtest overfitting
      </h2>
      <FigureStrip
        label="PBO"
        figures={[
          { label: "PBO", value: <span data-testid="pbo-value">{pctText(pbo.pbo)}</span> },
          { label: "Combinations", value: pbo.combinations.toLocaleString("en-US") },
          { label: "Out-of-sample loss", value: pctText(pbo.prob_oos_loss), note: "of the chosen" },
          { label: "Median logit", value: pbo.logit_median.toFixed(2) },
        ]}
      />
      <div
        className="flex h-28 items-end gap-1 border-b border-border-muted"
        role="img"
        aria-label={`Logit histogram: ${pbo.histogram.map((b) => `${b.count} from ${b.lo} to ${b.hi}`).join(", ")}.`}
      >
        {pbo.histogram.map((b) => (
          <div key={b.lo} className="flex h-full flex-1 flex-col justify-end">
            <div
              className={b.hi <= 0 ? "bg-negative/60" : "bg-brand/60"}
              style={{ height: `${(b.count / most) * 100}%` }}
              title={`${b.lo} to ${b.hi}: ${b.count}`}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between font-mono text-3xs text-text-tertiary">
        <span>-4</span>
        <span>logit 0 (median)</span>
        <span>+4</span>
      </div>
      <p className="text-xs leading-5 text-text-tertiary">
        {pbo.sessions} sessions split into {pbo.blocks} blocks of {pbo.block_sessions}
        {pbo.dropped_sessions ? ` (oldest ${pbo.dropped_sessions} dropped)` : ""}. For every way to
        pick half the blocks as in-sample, the setting with the best in-sample Sharpe is ranked
        among the {pbo.settings} out of sample; the logit is ln(w / (1 - w)) of its relative rank w.
        PBO is the share of logits at or below 0: how often the in-sample best did no better than
        the median out of sample (Bailey, Borwein, López de Prado and Zhu, 2017).
      </p>
    </section>
  );
}

export function PlateauHeatmap({ plateaus }: { plateaus: Record<string, Plateau | null> }) {
  const metrics = Object.keys(plateaus).filter((k) => plateaus[k]);
  const [metric, setMetric] = useState(metrics.includes("sharpe") ? "sharpe" : metrics[0]);
  const p = metric ? plateaus[metric] : null;
  if (!p) return null;
  const share = heatShare(p);
  return (
    <section className="space-y-2" aria-labelledby="plateau-heading" data-testid="plateau">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="plateau-heading" className="text-sm font-semibold">
          Parameter plateau
        </h2>
        <fieldset className="flex gap-1 text-xs">
          <legend className="sr-only">Metric</legend>
          {metrics.map((m) => (
            <label
              key={m}
              className="cursor-pointer rounded-full border border-border-muted px-2 py-0.5 has-checked:border-brand"
            >
              <input
                type="radio"
                name="plateau-metric"
                value={m}
                checked={metric === m}
                onChange={() => setMetric(m)}
                className="sr-only"
              />
              {m === "sharpe" ? "Net Sharpe" : "Net return"}
            </label>
          ))}
        </fieldset>
      </div>
      {p.isolated ? (
        <p className="text-sm text-warning" data-testid="plateau-isolated">
          The best setting is an isolated peak: {p.within} of {p.neighbours} neighbours hold up.
          Nearby settings do much worse, which is what an overfit setting looks like.
        </p>
      ) : (
        <p className="text-sm text-text-secondary" data-testid="plateau-ok">
          The best setting sits on a plateau: {p.within} of {p.neighbours} neighbours are within{" "}
          {pctText(p.tolerance, 0)} of it.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-1 text-xs">
          <caption className="sr-only">
            {metric === "sharpe" ? "Net Sharpe" : "Net return"} by{" "}
            {PARAM_LABEL[p.x_param] ?? p.x_param} (columns) and{" "}
            {PARAM_LABEL[p.y_param] ?? p.y_param} (rows)
          </caption>
          <thead>
            <tr>
              <th scope="col" className="text-left text-2xs font-normal text-text-tertiary">
                {PARAM_LABEL[p.y_param] ?? p.y_param} ↓ / {PARAM_LABEL[p.x_param] ?? p.x_param} →
              </th>
              {p.x_values.map((x) => (
                <th key={x} scope="col" className="px-2 font-mono font-normal text-text-tertiary">
                  {x}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {p.y_values.map((yv, j) => (
              <tr key={yv}>
                <th
                  scope="row"
                  className="pr-2 text-right font-mono font-normal text-text-tertiary"
                >
                  {yv}
                </th>
                {p.x_values.map((xv, i) => {
                  const v = p.cells[j]?.[i] ?? null;
                  const s = share[j]?.[i] ?? null;
                  const best = xv === p.best.x && yv === p.best.y;
                  return (
                    <td
                      key={xv}
                      className={`min-w-14 rounded-md px-2 py-2 text-center font-mono ${best ? "outline-2 outline-brand" : ""}`}
                      style={
                        s === null
                          ? undefined
                          : {
                              backgroundColor: `color-mix(in oklab, var(--brand) ${Math.round(10 + s * 60)}%, transparent)`,
                            }
                      }
                      data-best={best || undefined}
                    >
                      {formatPlateauValue(p.metric, v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs leading-5 text-text-tertiary">
        Darker is better; the outlined cell is the best. {p.rule}
      </p>
    </section>
  );
}
