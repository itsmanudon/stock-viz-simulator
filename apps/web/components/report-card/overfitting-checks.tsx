"use client";

/**
 * A4.3: "Overfitting checks" under a result. How many variants of this
 * strategy family were tried (the trial ledger), PSR and the Deflated Sharpe
 * Ratio in plain words, and the locked holdout with its one-time unlock (a
 * two-step confirm). The ledger and unlock are read at response time.
 */

import { useState, useTransition } from "react";

import { unlockHoldoutAction } from "@/app/(product)/backtest/holdout-actions";
import { FigureStrip } from "@/components/figure-strip";
import { FormulaTip } from "@/components/report-card/report-card";
import { ResearchSectionHeader } from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
import { formatUtcDateTime } from "@/lib/api-time";
import type { BacktestRequest } from "@/lib/api/types";
import {
  type OverfittingChecks as Checks,
  type HoldoutStatus,
  type ReportCard,
  pctText,
  probabilityWords,
  signedPct,
} from "@/lib/report-card";
import type { StrategyRequest } from "@/lib/rule-strategy";

export function OverfittingChecks({
  checks,
  report,
  request,
}: {
  checks: Checks;
  report?: ReportCard | null;
  /** The request on screen, to unlock its family's holdout. */
  request?: { backtest?: BacktestRequest; strategy?: StrategyRequest };
}) {
  const [current, setCurrent] = useState(checks);
  const { trials, dsr } = current;
  const psr = report?.sharpe.psr ?? null;
  return (
    <section
      aria-labelledby="overfit-heading"
      className="space-y-3"
      data-testid="overfitting-checks"
    >
      <ResearchSectionHeader
        id="overfit-heading"
        title="Overfitting checks"
        description={`${trials.family_label}: ${trials.n} variant${trials.n === 1 ? "" : "s"} tried${trials.scope === "anonymous" ? " (all signed-out visitors together)" : " by you"}.`}
      />
      <FigureStrip
        label="Overfitting checks"
        figures={[
          {
            label: "Variants tried (N)",
            value: <span data-testid="trials-n">{trials.n}</span>,
            note: `${trials.runs} run${trials.runs === 1 ? "" : "s"} recorded`,
          },
          {
            label: "PSR",
            value: psr === null ? "n/a" : pctText(psr),
            note: (
              <FormulaTip
                label={probabilityWords(psr)}
                formula={report?.sharpe.formula ?? "Probabilistic Sharpe ratio against 0"}
              />
            ),
          },
          {
            label: "DSR",
            value: (
              <span data-testid="dsr-value">
                {dsr.value === null || dsr.value === undefined ? "n/a" : pctText(dsr.value)}
              </span>
            ),
            note: <FormulaTip label={probabilityWords(dsr.value)} formula={dsr.formula} />,
          },
          {
            label: "Best-of-N bar",
            value: dsr.expected_max_sharpe_annual.toFixed(2),
            note: "Sharpe luck alone would show",
          },
        ]}
      />
      <div className="space-y-1 text-sm leading-6 text-text-secondary">
        <p data-testid="dsr-meaning">{dsr.meaning}</p>
        <p className="text-xs text-text-tertiary">
          {dsr.note} Inputs: annual Sharpe {dsr.sharpe_annual.toFixed(2)} over {dsr.observations}{" "}
          days, skewness {dsr.skewness?.toFixed(2) ?? "n/a"}, kurtosis{" "}
          {dsr.kurtosis?.toFixed(2) ?? "n/a"}
          {dsr.variance
            ? `, variance of the variants' daily Sharpes ${dsr.variance.toExponential(2)}`
            : ""}
          .
        </p>
        <details className="text-xs text-text-tertiary">
          <summary className="cursor-pointer hover:text-foreground">
            What counts as a variant
          </summary>
          <p className="mt-1">{trials.definition}</p>
        </details>
      </div>
      <HoldoutPanel holdout={current.holdout} request={request} onUnlocked={setCurrent} />
    </section>
  );
}

function HoldoutPanel({
  holdout,
  request,
  onUnlocked,
}: {
  holdout: HoldoutStatus;
  request?: { backtest?: BacktestRequest; strategy?: StrategyRequest };
  onUnlocked: (checks: Checks) => void;
}) {
  const [step, setStep] = useState<"idle" | "confirm">("idle");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const range =
    holdout.holdout_from && holdout.holdout_to
      ? `${holdout.holdout_from} to ${holdout.holdout_to}`
      : null;
  const title =
    holdout.status === "locked"
      ? "Holdout locked"
      : holdout.status === "seen"
        ? "Holdout seen"
        : "No holdout";

  function unlock() {
    if (!request) return;
    setError(null);
    start(async () => {
      const res = await unlockHoldoutAction(request);
      if (res.checks) {
        onUnlocked(res.checks);
        setStep("idle");
      } else {
        setError(res.error ?? "The holdout could not be unlocked.");
      }
    });
  }

  return (
    <div
      className="rounded-xl border border-border-muted bg-card p-4"
      data-testid="holdout-panel"
      data-status={holdout.status}
    >
      <h3 className="text-sm font-semibold">
        {title}
        {range ? <span className="ml-2 font-mono text-xs text-text-tertiary">{range}</span> : null}
      </h3>
      <p className="mt-1 text-xs leading-5 text-text-secondary">{holdout.note}</p>
      {holdout.status === "seen" && holdout.unlocked_at ? (
        <p className="mt-1 text-xs text-text-tertiary">
          Unlocked {formatUtcDateTime(holdout.unlocked_at)}.
        </p>
      ) : null}
      {holdout.result ? (
        <FigureStrip
          className="mt-3"
          label="Holdout result"
          figures={[
            { label: "Holdout net return", value: signedPct(holdout.result.total_return) },
            { label: "Sharpe", value: holdout.result.sharpe.toFixed(2) },
            {
              label: "Max drawdown",
              value: <span className="text-negative">-{pctText(holdout.result.max_drawdown)}</span>,
            },
            {
              label: "PSR",
              value:
                holdout.result.psr === null || holdout.result.psr === undefined
                  ? "n/a"
                  : pctText(holdout.result.psr),
            },
            { label: "Trades", value: String(holdout.result.trades) },
          ]}
        />
      ) : null}
      {holdout.status === "locked" && holdout.can_unlock && request ? (
        step === "idle" ? (
          <Button
            type="button"
            variant="outline"
            className="mt-3"
            onClick={() => setStep("confirm")}
            data-testid="holdout-unlock"
          >
            Unlock holdout…
          </Button>
        ) : (
          <fieldset className="mt-3 space-y-2" aria-label="Confirm the unlock">
            <p className="text-xs leading-5 text-warning">
              This can be done once for this strategy family. After it, every run of the family
              shows the holdout as seen, and results on it stop counting as out of sample.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={unlock}
                disabled={pending}
                data-testid="holdout-confirm"
                autoFocus
              >
                {pending ? "Unlocking…" : "Unlock once, now"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setStep("idle")}>
                Cancel
              </Button>
            </div>
          </fieldset>
        )
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-negative">
          {error}
        </p>
      ) : null}
    </div>
  );
}
