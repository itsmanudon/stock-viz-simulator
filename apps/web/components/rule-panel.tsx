"use client";

import Link from "next/link";
import { useActionState, useEffect, useId, useRef, useState } from "react";

import {
  type SetupActionState,
  forkPresetAction,
  saveSetupAction,
} from "@/app/(product)/screener/actions";
import { RuleBuilder } from "@/components/rule-builder";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type RuleCheck, checkRule } from "@/lib/api/rules";
import { drillLaunchHref } from "@/lib/drills";
import { eventStudyHref } from "@/lib/event-study";
import { type RuleMode, describeRuleError, warmupLabel } from "@/lib/screener-view";

export type RulePreset = {
  id: number;
  name: string;
  description: string | null;
  rule: string;
};

type Check =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "done"; result: RuleCheck }
  | { state: "failed" };

const DEBOUNCE_MS = 400;

const EXAMPLE = "close > sma(close, 200) and rsi(14) < 70";

/**
 * The screener's Rule panel (A2.2, M4.3). A Rule DSL condition refines the
 * filters: the form is a GET to /screener, so the rule lives in the URL
 * (`?rule=`, `?rule_mode=`) and a screen with a rule is a shareable link. The
 * filters and sort ride along as hidden fields.
 *
 * As the user types, the rule is checked against `POST /v1/rules/check`
 * (debounced, from the browser): an error is shown with its line and a
 * caret under its column; a valid rule shows its canonical form and warm-up.
 * Signed-in users can save the rule as a setup, and fork a preset.
 */
export function RulePanel({
  rule,
  mode,
  carried,
  presets,
  signedIn,
  clearHref,
  check = checkRule,
}: {
  rule: string;
  mode: RuleMode;
  carried: [string, string][];
  presets: RulePreset[];
  signedIn: boolean;
  clearHref: string | null;
  check?: (rule: string, signal?: AbortSignal) => Promise<RuleCheck>;
}) {
  const id = useId();
  const [text, setText] = useState(rule);
  const [status, setStatus] = useState<Check>({ state: "idle" });
  const [presetId, setPresetId] = useState<string>("");
  const formRef = useRef<HTMLFormElement>(null);
  const [saveState, save, saving] = useActionState<SetupActionState, FormData>(saveSetupAction, {});
  const [forkState, fork, forking] = useActionState<SetupActionState, FormData>(
    forkPresetAction,
    {},
  );

  useEffect(() => {
    const value = text.trim();
    if (!value) {
      setStatus({ state: "idle" });
      return;
    }
    const controller = new AbortController();
    setStatus({ state: "checking" });
    const timer = setTimeout(() => {
      check(value, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setStatus({ state: "done", result });
        })
        .catch(() => {
          if (!controller.signal.aborted) setStatus({ state: "failed" });
        });
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [text, check]);

  const result = status.state === "done" ? status.result : null;
  const invalid = result !== null && !result.valid;
  const valid = result?.valid === true;
  const preset = presets.find((p) => String(p.id) === presetId) ?? null;

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="mb-4 space-y-3 rounded-md border border-border-muted bg-card p-4 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2
            id={`${id}-title`}
            className="text-2xs font-semibold tracking-[0.02em] text-text-tertiary"
          >
            Rule
          </h2>
          <p className="mt-1 text-xs text-text-secondary">
            Filters narrow the list first; the rule then judges each symbol on its latest completed
            session.
          </p>
        </div>
        {clearHref ? (
          <Link
            href={clearHref}
            className="text-xs text-text-secondary hover:text-foreground hover:underline"
          >
            Clear rule
          </Link>
        ) : null}
      </div>

      {presets.length ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 space-y-1">
            <Label htmlFor={`${id}-preset`} className="text-xs">
              Presets
            </Label>
            <select
              id={`${id}-preset`}
              value={presetId}
              onChange={(e) => setPresetId(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
            >
              <option value="">Choose a preset…</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={!preset}
            onClick={() => preset && setText(preset.rule)}
          >
            Load
          </Button>
          {signedIn ? (
            <form action={fork}>
              <input type="hidden" name="id" value={preset?.id ?? ""} />
              <Button type="submit" variant="outline" disabled={!preset || forking}>
                {forking ? "Forking…" : "Fork"}
              </Button>
            </form>
          ) : null}
        </div>
      ) : null}
      {preset?.description ? (
        <p className="text-xs leading-5 text-text-tertiary" data-testid="preset-description">
          {preset.description}
        </p>
      ) : null}
      {forkState.saved ? (
        <output className="block text-xs">
          Forked into “{forkState.saved.name}”.{" "}
          <Link href="/setups" className="underline">
            Your setups
          </Link>
        </output>
      ) : null}
      {forkState.error ? (
        <p role="alert" className="text-xs text-negative">
          {forkState.error}
        </p>
      ) : null}

      <details className="text-xs text-text-secondary" data-testid="build-visually">
        <summary className="cursor-pointer text-text-tertiary hover:text-foreground">
          Build visually
        </summary>
        <p className="mt-2 leading-5 text-text-tertiary">
          Each change writes the rule above; you can edit the text after.
        </p>
        <div className="mt-2">
          <RuleBuilder onRule={setText} />
        </div>
      </details>

      <details className="text-xs text-text-secondary">
        <summary className="cursor-pointer text-text-tertiary hover:text-foreground">
          How to write a rule
        </summary>
        <ul className="mt-2 space-y-1 font-mono text-2xs leading-5">
          <li>close &gt; sma(close, 200) and sma(close, 50) &gt; sma(close, 200)</li>
          <li>rsi(14) &lt; 30 and volume &gt; 2 * sma(volume, 20)</li>
          <li>close &gt;= highest(high, 252)[1]</li>
          <li>weekly.close crosses_above weekly.ema(close, 10)</li>
          <li>fundamental.pe &lt; 25 and fundamental.roe &gt; 15</li>
          <li>rs(126) &gt; 0</li>
        </ul>
        <p className="mt-2 leading-5">
          Comparisons, and/or/not, [n] for n bars ago, weekly. and monthly. for closed weeks and
          months. A symbol whose data is missing shows as unknown, never as not met.
        </p>
      </details>

      <form ref={formRef} method="GET" action="/screener" className="space-y-3">
        {carried.map(([key, value]) => (
          <input key={key} type="hidden" name={key} value={value} />
        ))}
        <div className="space-y-1">
          <Label htmlFor={`${id}-rule`} className="text-xs">
            Rule text
          </Label>
          <textarea
            id={`${id}-rule`}
            name="rule"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Ctrl/Cmd+Enter runs the rule, as in a query editor.
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !invalid) {
                e.preventDefault();
                formRef.current?.requestSubmit();
              }
            }}
            rows={4}
            spellCheck={false}
            autoCapitalize="off"
            autoComplete="off"
            placeholder={EXAMPLE}
            aria-invalid={invalid}
            aria-describedby={`${id}-status`}
            className="w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs leading-5 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 aria-[invalid=true]:border-negative"
          />
        </div>

        <div id={`${id}-status`} aria-live="polite" className="min-h-5 text-xs">
          <RuleStatus status={status} text={text} signedIn={signedIn} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <fieldset className="flex flex-wrap gap-3">
            <legend className="sr-only">Rows to show</legend>
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="radio"
                name="rule_mode"
                value="met_only"
                defaultChecked={mode === "met_only"}
                className="accent-brand"
              />
              Met only
            </label>
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="radio"
                name="rule_mode"
                value="all"
                defaultChecked={mode === "all"}
                className="accent-brand"
              />
              Show all with result
            </label>
          </fieldset>
          <Button type="submit" disabled={invalid}>
            Run
          </Button>
          {valid && text.trim() ? (
            <Link
              href={eventStudyHref({ rule: text.trim() })}
              className="text-xs text-text-secondary underline hover:text-foreground"
              data-testid="rule-event-study"
            >
              Run event study
            </Link>
          ) : null}
          {valid && text.trim() && signedIn ? (
            <Link
              href={drillLaunchHref({ rule: text.trim(), market: "US" })}
              className="text-xs text-text-secondary underline hover:text-foreground"
              data-testid="rule-drill"
            >
              Drill this setup
            </Link>
          ) : null}
        </div>
      </form>

      {signedIn ? (
        <form action={save} className="flex flex-wrap gap-2 border-t border-border-muted pt-3">
          <input type="hidden" name="rule" value={text} />
          <Input
            name="name"
            aria-label="Name for this setup"
            placeholder="Name this setup"
            className="min-w-0 flex-1"
            maxLength={120}
          />
          <Button type="submit" variant="outline" disabled={!valid || saving}>
            {saving ? "Saving…" : "Save as setup"}
          </Button>
          {saveState.saved ? (
            <output className="block w-full text-xs">
              Saved “{saveState.saved.name}” (version {saveState.saved.version}).{" "}
              <Link href="/setups" className="underline">
                Your setups
              </Link>
            </output>
          ) : null}
          {saveState.error ? (
            <p role="alert" className="w-full text-xs text-negative">
              {saveState.error}
            </p>
          ) : null}
        </form>
      ) : (
        <p className="border-t border-border-muted pt-3 text-xs text-text-tertiary">
          <Link href="/login?callbackUrl=/screener" className="underline">
            Sign in
          </Link>{" "}
          to save rules as setups and fork presets.
        </p>
      )}
    </section>
  );
}

function RuleStatus({
  status,
  text,
  signedIn,
}: {
  status: Check;
  text: string;
  signedIn: boolean;
}) {
  if (status.state === "idle") {
    return <span className="text-text-tertiary">Write a condition, for example {EXAMPLE}.</span>;
  }
  if (status.state === "checking") return <span className="text-text-tertiary">Checking…</span>;
  if (status.state === "failed") {
    return (
      <span className="text-text-tertiary">
        The rule could not be checked just now. Run still works.
      </span>
    );
  }
  const { result } = status;
  if (!result.valid && result.error) {
    const { line, column } = result.error;
    const lines = text.split("\n");
    const shown = line && line >= 1 && line <= lines.length ? lines[line - 1] : null;
    return (
      <div role="alert" className="space-y-1 text-negative">
        <p>{describeRuleError(result.error)}</p>
        {shown !== null && column ? (
          <pre
            aria-hidden
            className="overflow-x-auto rounded bg-surface-secondary p-2 font-mono text-2xs leading-4 text-foreground"
          >
            {shown}
            {"\n"}
            {`${" ".repeat(Math.max(0, column - 1))}^`}
          </pre>
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-0.5 text-text-secondary">
      <p>
        <span className="font-medium text-positive">Valid.</span>{" "}
        {warmupLabel(result.warmup_bars, result.warmup_whole_history ?? false)}
        {result.uses?.length ? `; reads ${result.uses.join(", ")}` : ""}.
      </p>
      <p className="break-words font-mono text-2xs text-text-tertiary" data-testid="canonical">
        {result.canonical}
      </p>
      {result.user_scoped ? (
        <p className="text-2xs text-text-secondary" data-testid="rule-user-scoped">
          {signedIn
            ? "Uses your drawings; only you can run it. Symbols without the named drawing are unknown."
            : "Uses drawings, which belong to one person: sign in to run it on yours."}
        </p>
      ) : null}
    </div>
  );
}
