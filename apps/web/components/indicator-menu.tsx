"use client";

/**
 * The chart's Indicators menu (A3.4, M2.6): the selected studies with their
 * parameters, editable in place, and every other study to add, each with
 * its evidence badge.
 *
 * - Parameters are number inputs (or a select for an option, like the pivot
 *   basis) with the catalog's bounds; Enter or "Apply" writes the new key to
 *   the URL (`rsi_21`, `bb_20_2.5`), "Reset" puts the defaults back, and an
 *   out-of-bounds value says why and is not applied.
 * - A popover, not a menu: its inputs take typing, Tab moves through it and
 *   Escape closes it.
 * - Without the catalog (its call failed) studies can still be added and
 *   removed at their defaults; parameters and badges need it.
 */

import { ChevronDown, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { Popover } from "radix-ui";
import { type FormEvent, useId, useMemo, useState } from "react";

import type { IndicatorCatalogItem, IndicatorParam } from "@/lib/api/types";
import { ASSOCIATION_NOTE, type IndicatorBadge, indicatorBadge } from "@/lib/indicator-badge";
import {
  STOCK_INDICATORS,
  type StockIndicator,
  buildIndicatorKey,
  indicatorLabel,
  paramError,
  parseIndicatorKey,
} from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export function EvidenceBadge({ badge, className }: { badge: IndicatorBadge; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-1.5 font-mono text-3xs leading-4 whitespace-nowrap",
        badge.graded ? "border-border text-foreground" : "border-border-muted text-text-tertiary",
        className,
      )}
      title={badge.title}
      data-testid="evidence-badge"
      data-graded={badge.graded ? "true" : "false"}
    >
      <span aria-hidden>{badge.graded ? `Grade ${badge.text}` : badge.text}</span>
      <span className="sr-only">{badge.title}</span>
    </span>
  );
}

/** The key a set of values makes: MACD at its defaults stays `macd` (the API's MACD field). */
export function keyFor(item: IndicatorCatalogItem, values: number[]): string {
  const defaults = item.parameters.map((p) => p.default);
  if (item.key === "macd" && values.every((v, i) => v === defaults[i])) return "macd";
  return item.parameters.length ? buildIndicatorKey(item.key, values) : item.key;
}

/** The values a key carries, defaults filling any left out. */
export function valuesFor(item: IndicatorCatalogItem, key: string): number[] {
  const given = parseIndicatorKey(key)?.values ?? [];
  return item.parameters.map((p, i) => given[i] ?? p.default);
}

function ParamField({
  param,
  value,
  error,
  onChange,
  study,
}: {
  param: IndicatorParam;
  value: string;
  error: string | null;
  onChange: (value: string) => void;
  study: string;
}) {
  const id = useId();
  const name = param.label || param.name;
  if (param.choices.length) {
    return (
      <label className="flex flex-col gap-0.5 text-3xs text-text-tertiary" htmlFor={id}>
        {name}
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label={`${study} ${name}`}
          className="h-7 rounded-sm border border-border-muted bg-card px-1.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
        >
          {param.choices.map((choice, i) => (
            <option key={choice} value={String(i + 1)}>
              {choice}
            </option>
          ))}
        </select>
      </label>
    );
  }
  const min = param.type === "float" && param.min_exclusive ? param.min + param.step : param.min;
  return (
    <label className="flex flex-col gap-0.5 text-3xs text-text-tertiary" htmlFor={id}>
      {name}
      <input
        id={id}
        type="number"
        inputMode={param.type === "int" ? "numeric" : "decimal"}
        min={min}
        max={param.max}
        step={param.step}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={`${study} ${name}`}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={cn(
          "h-7 w-[4.5rem] rounded-sm border bg-card px-1.5 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60",
          error ? "border-negative" : "border-border-muted",
        )}
      />
      {error ? (
        <span id={`${id}-error`} className="text-3xs text-negative">
          {error}
        </span>
      ) : null}
    </label>
  );
}

/** One selected study: its badge, parameters, Apply, Reset and Remove. */
export function StudyEditor({
  item,
  studyKey,
  onApply,
  onRemove,
}: {
  item: IndicatorCatalogItem | undefined;
  studyKey: string;
  onApply: (next: string) => void;
  onRemove: () => void;
}) {
  const label = indicatorLabel(studyKey);
  const initial = useMemo(
    () => (item ? valuesFor(item, studyKey).map(String) : []),
    [item, studyKey],
  );
  const [draft, setDraft] = useState<string[]>(initial);
  const badge = indicatorBadge(item, studyKey);
  const errors = item ? item.parameters.map((p, i) => paramError(p, Number(draft[i] ?? ""))) : [];
  const defaults = item?.parameters.map((p) => String(p.default)) ?? [];
  const atDefaults = draft.every((v, i) => Number(v) === Number(defaults[i]));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!item || errors.some(Boolean)) return;
    const next = keyFor(item, draft.map(Number));
    if (next !== studyKey) onApply(next);
  }

  return (
    <li className="rounded-md border border-border-muted p-2" data-testid="study-editor">
      <form onSubmit={submit} aria-label={`${label} parameters`}>
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
            {label}
          </span>
          <EvidenceBadge badge={badge} />
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${label}`}
            title={`Remove ${label}`}
            className="inline-flex size-6 items-center justify-center rounded-sm text-text-tertiary hover:bg-surface-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
        {item?.parameters.length ? (
          <div className="mt-2 flex flex-wrap items-end gap-2">
            {item.parameters.map((param, i) => (
              <ParamField
                key={param.name}
                param={param}
                study={label}
                value={draft[i] ?? ""}
                error={errors[i]}
                onChange={(value) => setDraft((prev) => prev.map((v, j) => (j === i ? value : v)))}
              />
            ))}
            <button
              type="submit"
              disabled={errors.some(Boolean)}
              className="h-7 rounded-sm bg-brand/12 px-2 text-xs font-medium text-brand hover:bg-brand/20 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
            >
              Apply
            </button>
            <button
              type="button"
              disabled={atDefaults}
              onClick={() => {
                setDraft(defaults);
                if (item) {
                  const next = keyFor(item, defaults.map(Number));
                  if (next !== studyKey) onApply(next);
                }
              }}
              aria-label={`Reset ${label} to defaults`}
              className="inline-flex h-7 items-center gap-1 rounded-sm px-1.5 text-xs text-text-secondary hover:bg-surface-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
            >
              <RotateCcw className="size-3" aria-hidden />
              Reset
            </button>
          </div>
        ) : null}
        {item?.signal ? (
          <p className="mt-1.5 text-3xs leading-4 text-text-tertiary" data-testid="study-signal">
            {item.signal.description}. {badge.graded ? null : `${badge.text}. `}
            {item.signal.evidence
              ? `${item.signal.evidence.n_events} events, ${item.signal.evidence.horizon} sessions after each. ${ASSOCIATION_NOTE}`
              : null}
          </p>
        ) : null}
      </form>
    </li>
  );
}

export function IndicatorMenu({
  indicators,
  catalog,
  onChange,
}: {
  indicators: StockIndicator[];
  catalog?: IndicatorCatalogItem[] | null;
  onChange: (next: StockIndicator[]) => void;
}) {
  const [filter, setFilter] = useState("");
  const byKey = useMemo(() => new Map((catalog ?? []).map((item) => [item.key, item])), [catalog]);
  const query = filter.trim().toLowerCase();
  const available = STOCK_INDICATORS.filter(
    (study) =>
      !query ||
      study.label.toLowerCase().includes(query) ||
      study.key.includes(query) ||
      study.group.includes(query),
  );
  const sections = [
    { section: "price", title: "On the price chart" },
    { section: "pane", title: "Below the chart" },
  ] as const;

  function add(study: (typeof STOCK_INDICATORS)[number]) {
    const key = byKey.get(study.key)?.default_key ?? study.value;
    const normal = study.key === "macd" ? "macd" : key;
    if (!indicators.includes(normal)) onChange([...indicators, normal]);
  }

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-2 rounded-md border border-border-muted px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground data-[state=open]:bg-surface-hover data-[state=open]:text-foreground"
          aria-label={`Indicators, ${indicators.length} selected`}
        >
          <SlidersHorizontal className="size-3.5" aria-hidden />
          Indicators
          {indicators.length ? (
            <span className="font-mono text-3xs text-brand">{indicators.length}</span>
          ) : null}
          <ChevronDown className="size-3" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          className="z-50 flex max-h-[min(44rem,var(--radix-popover-content-available-height))] w-[22rem] max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-md border border-border-muted bg-popover"
          data-testid="indicator-menu"
        >
          <div className="overflow-y-auto p-2">
            <h2 className="px-1 pb-1.5 text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
              On the Chart
            </h2>
            {indicators.length ? (
              <ul className="space-y-1.5" aria-label="Selected studies">
                {indicators.map((key) => (
                  <StudyEditor
                    // A new key remounts the editor with its values.
                    key={key}
                    studyKey={key}
                    item={byKey.get(parseIndicatorKey(key)?.base ?? "")}
                    onApply={(next) =>
                      onChange(
                        indicators.includes(next)
                          ? indicators.filter((k) => k !== key)
                          : indicators.map((k) => (k === key ? next : k)),
                      )
                    }
                    onRemove={() => onChange(indicators.filter((k) => k !== key))}
                  />
                ))}
              </ul>
            ) : (
              <p className="px-1 text-xs text-text-tertiary">No studies on the chart.</p>
            )}

            <div className="mt-3 border-t border-border-muted pt-2">
              <label className="block px-1 text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                Add a Study
                <input
                  type="search"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter by name or group"
                  aria-label="Filter studies"
                  className="mt-1 h-7 w-full rounded-sm border border-border-muted bg-card px-2 text-xs font-normal normal-case tracking-normal text-foreground placeholder:text-text-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
                />
              </label>
              {sections.map(({ section, title }) => {
                const studies = available.filter((s) => s.section === section);
                if (!studies.length) return null;
                return (
                  <div key={section} className="mt-2">
                    <h3 className="px-1 pb-1 text-3xs text-text-tertiary">{title}</h3>
                    <ul className="grid grid-cols-1 gap-0.5">
                      {studies.map((study) => {
                        const item = byKey.get(study.key);
                        const key = item?.default_key ?? study.value;
                        const added = indicators.includes(study.key === "macd" ? "macd" : key);
                        return (
                          <li key={study.key}>
                            <button
                              type="button"
                              onClick={() => add(study)}
                              disabled={added}
                              aria-label={added ? `${study.label} (added)` : `Add ${study.label}`}
                              className="flex h-7 w-full items-center gap-2 rounded-sm px-2 text-left text-xs text-muted-foreground hover:bg-surface-hover hover:text-foreground disabled:cursor-default disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
                              data-testid="add-study"
                              data-study={study.key}
                            >
                              <span className="min-w-0 flex-1 truncate">{study.label}</span>
                              {catalog ? <EvidenceBadge badge={indicatorBadge(item)} /> : null}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
              <p className="mt-2 px-1 text-3xs leading-4 text-text-tertiary">
                Grades rate each study&apos;s canonical signal on its default parameters: the 20
                sessions after, net of fees, against the universe on the same dates.{" "}
                {ASSOCIATION_NOTE}
              </p>
            </div>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
