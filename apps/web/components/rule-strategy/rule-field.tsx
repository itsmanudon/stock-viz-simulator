"use client";

/**
 * A4.1: one rule of a Rule strategy (entry or exit). A textarea checked as
 * the user types (`checkRule()`, 400 ms debounce, the last request aborted,
 * as the screener's Rule panel does), and a setup picker that loads a saved
 * version (yours or a preset's). A loaded version is sent by id until the
 * text is edited; then it is inline text, saved as a version when the run
 * is saved.
 */

import { useEffect, useId, useState } from "react";

import { Label } from "@/components/ui/label";
import { type RuleCheck, type RuleTimeframe, checkRule } from "@/lib/api/rules";
import type { RuleField } from "@/lib/rule-strategy";
import { describeRuleError, warmupLabel } from "@/lib/screener-view";

export type StrategySetupOption = {
  versionId: number;
  name: string;
  rule: string;
  preset: boolean;
  /** A6.4: the version's timeframe (daily when absent). */
  timeframe?: string;
};

type Check =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "done"; result: RuleCheck }
  | { state: "failed" };

const DEBOUNCE_MS = 400;

export function RuleFieldEditor({
  label,
  hint,
  value,
  onChange,
  onValidity,
  setups,
  optional = false,
  check = checkRule,
  timeframe = "daily",
}: {
  label: string;
  hint: string;
  value: RuleField;
  onChange: (next: RuleField) => void;
  /** Called with false while the text is invalid (empty optional text is valid). */
  onValidity: (valid: boolean) => void;
  setups: StrategySetupOption[];
  optional?: boolean;
  check?: (
    rule: string,
    signal?: AbortSignal,
    expect?: "condition" | "number",
    timeframe?: RuleTimeframe,
  ) => Promise<RuleCheck>;
  /** A6.4: the rule is checked for these bars. */
  timeframe?: RuleTimeframe;
}) {
  const id = useId();
  const [status, setStatus] = useState<Check>({ state: "idle" });

  useEffect(() => {
    const text = value.text.trim();
    if (!text) {
      setStatus({ state: "idle" });
      onValidity(optional);
      return;
    }
    const controller = new AbortController();
    setStatus({ state: "checking" });
    const timer = setTimeout(() => {
      check(text, controller.signal, "condition", timeframe)
        .then((result) => {
          if (controller.signal.aborted) return;
          setStatus({ state: "done", result });
          onValidity(result.valid);
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setStatus({ state: "failed" });
          onValidity(true); // the API checks again on run
        });
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [value.text, check, optional, onValidity, timeframe]);

  const result = status.state === "done" ? status.result : null;
  // A6.4: only versions judged on the same bars can be loaded.
  const usable = setups.filter((s) => (s.timeframe ?? "daily") === timeframe);
  const yours = usable.filter((s) => !s.preset);
  const presets = usable.filter((s) => s.preset);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <Label htmlFor={`${id}-rule`}>{label}</Label>
        {usable.length ? (
          <select
            aria-label={`Load a setup into the ${label.toLowerCase()}`}
            value={value.versionId ?? ""}
            onChange={(event) => {
              const picked = setups.find((s) => String(s.versionId) === event.target.value);
              if (picked) onChange({ text: picked.rule, versionId: picked.versionId });
            }}
            className="h-8 max-w-[14rem] rounded-sm border border-input bg-transparent px-2 text-xs"
          >
            <option value="">Load a setup…</option>
            {yours.length ? (
              <optgroup label="Your setups">
                {yours.map((s) => (
                  <option key={s.versionId} value={s.versionId}>
                    {s.name}
                  </option>
                ))}
              </optgroup>
            ) : null}
            {presets.length ? (
              <optgroup label="Presets">
                {presets.map((s) => (
                  <option key={s.versionId} value={s.versionId}>
                    {s.name}
                  </option>
                ))}
              </optgroup>
            ) : null}
          </select>
        ) : null}
      </div>
      <textarea
        id={`${id}-rule`}
        value={value.text}
        onChange={(event) => onChange({ text: event.target.value, versionId: null })}
        rows={2}
        spellCheck={false}
        aria-describedby={`${id}-status`}
        aria-invalid={result ? !result.valid : undefined}
        placeholder={
          optional ? "Optional: stops alone can close" : "close crosses_above sma(close, 50)"
        }
        className="w-full rounded-sm border border-input bg-transparent px-3 py-2 font-mono text-xs leading-5"
      />
      <p id={`${id}-status`} className="text-xs leading-5 text-text-tertiary" aria-live="polite">
        {status.state === "checking" ? "Checking…" : null}
        {status.state === "failed" ? "Could not check the rule; it is checked again on run." : null}
        {status.state === "idle" ? hint : null}
        {result && !result.valid && result.error ? (
          <span className="text-negative" data-testid="rule-error">
            {describeRuleError(result.error)}
          </span>
        ) : null}
        {result?.valid ? (
          <span data-testid="rule-ok">
            <span className="font-mono">{result.canonical}</span> ·{" "}
            {warmupLabel(result.warmup_bars, result.warmup_whole_history)}
            {value.versionId !== null ? " · saved setup version" : ""}
          </span>
        ) : null}
      </p>
    </div>
  );
}
