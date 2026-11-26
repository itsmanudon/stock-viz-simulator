/**
 * The Checklist (A2.4, M4.4): six published conditions per symbol, each
 * met / not met / unknown, with its formula, its evidence grade and the
 * sample behind the grade. Server components only: expanding uses native
 * `<details>`, so it works without JavaScript and is keyboard-accessible.
 *
 * Wording is neutral: "N of 6 met". Status is always written as a word, never
 * shown by colour alone.
 */

import { StatusBadge } from "@/components/status-badge";
import { StrengthDots } from "@/components/strength-dots";
import { universeSummary } from "@/components/universe-note";
import type {
  ChecklistDimension,
  ChecklistEvidence,
  ChecklistResult,
  ChecklistRow,
  ChecklistStatus,
  ChecklistVariant,
} from "@/lib/api/types";
import {
  GRADE_BANDS,
  SCOPE_LABEL,
  STATUS_LABEL,
  evaluatedNote,
  evidenceFigures,
  evidenceSample,
  gradeLabel,
  metSummary,
  resultFor,
  statusTone,
  variantFor,
} from "@/lib/checklist-view";
import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";

export function ChecklistStatusBadge({ status }: { status: ChecklistStatus }) {
  return <StatusBadge label={STATUS_LABEL[status]} tone={statusTone(status)} />;
}

export function GradeBadge({ evidence }: { evidence: ChecklistEvidence | null | undefined }) {
  const graded = evidence && evidence.grade !== "insufficient";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-2xs whitespace-nowrap",
        graded ? "border-border text-foreground" : "border-border-muted text-text-tertiary",
      )}
      data-testid="grade-badge"
    >
      {gradeLabel(evidence)}
    </span>
  );
}

/** A grade with the sample it was measured on and its survivorship stamp. */
export function EvidenceNote({ evidence }: { evidence: ChecklistEvidence | null | undefined }) {
  if (!evidence) {
    return (
      <p className="text-xs leading-5 text-text-tertiary">
        Not graded yet: the weekly evidence study has not run on this formula.
      </p>
    );
  }
  return (
    <div className="space-y-1 text-xs leading-5 text-text-tertiary">
      <p>
        <span className="font-medium text-text-secondary">Sample:</span> {evidenceSample(evidence)}.
      </p>
      {evidence.grade !== "insufficient" ? <p>{evidenceFigures(evidence)}.</p> : null}
      <p data-testid="evidence-universe">
        <span className="font-medium text-text-secondary">Universe:</span>{" "}
        {universeSummary(evidence.universe)} {evidence.universe.note}
      </p>
    </div>
  );
}

function Formula({ variant }: { variant: ChecklistVariant }) {
  return (
    <ul className="space-y-1.5">
      {variant.conditions.map((condition) => (
        <li key={condition.rule} className="text-xs">
          <span className="text-text-secondary">{condition.label}</span>
          <code className="mt-0.5 block overflow-x-auto rounded-sm bg-muted px-1.5 py-0.5 font-mono text-2xs">
            {condition.rule}
          </code>
        </li>
      ))}
    </ul>
  );
}

/** Every dimension's definition: summary, source, formula per scope, grade. */
export function DimensionGuide({ dimensions }: { dimensions: ChecklistDimension[] }) {
  return (
    <section aria-labelledby="checklist-dimensions" className="space-y-2">
      <h2 id="checklist-dimensions" className="text-sm font-semibold tracking-tight">
        The six dimensions
      </h2>
      <p className="text-xs leading-5 text-text-tertiary">
        A dimension is met when every one of its conditions is met, unknown when an input is missing
        and none failed, otherwise not met. Grades: {GRADE_BANDS}
      </p>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {dimensions.map((dimension) => (
          <details
            key={dimension.key}
            className="group rounded-md border border-border-muted bg-card p-3"
            data-testid={`dimension-${dimension.key}`}
          >
            <summary className="flex cursor-pointer list-none items-start justify-between gap-2">
              <span>
                <span className="block text-sm font-medium">{dimension.name}</span>
                <span className="mt-0.5 block text-xs leading-5 text-text-tertiary">
                  {dimension.summary}
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                {dimension.variants.map((variant) => (
                  <GradeBadge key={variant.setup_version_id} evidence={variant.evidence} />
                ))}
              </span>
            </summary>
            <div className="mt-3 space-y-3 border-t border-border-muted pt-3">
              {dimension.variants.map((variant) => (
                <div key={variant.setup_version_id} className="space-y-2">
                  {dimension.variants.length > 1 ? (
                    <p className="text-2xs font-semibold tracking-[0.02em] text-text-tertiary">
                      {titleCase(SCOPE_LABEL[variant.scope])} · Version {variant.version}
                    </p>
                  ) : (
                    <p className="text-2xs font-semibold tracking-[0.02em] text-text-tertiary">
                      Version {variant.version}
                    </p>
                  )}
                  <Formula variant={variant} />
                  <EvidenceNote evidence={variant.evidence} />
                </div>
              ))}
              <p className="text-xs leading-5 text-text-tertiary">
                <span className="font-medium text-text-secondary">Source:</span> {dimension.source}
              </p>
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

function ResultDetail({
  dimension,
  result,
}: {
  dimension: ChecklistDimension;
  result: ChecklistResult | undefined;
}) {
  const variant = variantFor(dimension, result);
  const status = result?.status ?? "unknown";
  return (
    <div className="space-y-2 rounded-md border border-border-muted p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">{dimension.name}</span>
        <span className="flex items-center gap-2">
          <ChecklistStatusBadge status={status} />
          <GradeBadge evidence={variant?.evidence} />
        </span>
      </div>
      {result?.reason ? (
        <p className="text-xs leading-5 text-text-tertiary">{result.reason}</p>
      ) : null}
      <ul className="space-y-1.5">
        {(result?.conditions ?? []).map((condition) => (
          <li key={condition.rule} className="text-xs">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-text-secondary">{condition.label}</span>
              <span className="text-2xs font-medium text-text-tertiary">
                {STATUS_LABEL[condition.status]}
              </span>
            </span>
            <code className="mt-0.5 block overflow-x-auto rounded-sm bg-muted px-1.5 py-0.5 font-mono text-2xs">
              {condition.rule}
            </code>
            {condition.status === "unknown" && condition.reason ? (
              <span className="mt-0.5 block text-2xs text-text-tertiary">{condition.reason}</span>
            ) : null}
          </li>
        ))}
      </ul>
      {variant ? <EvidenceNote evidence={variant.evidence} /> : null}
    </div>
  );
}

/** One symbol as an expandable card: the count, six statuses, then the detail. */
export function ChecklistSymbol({
  row,
  dimensions,
  open = false,
}: {
  row: ChecklistRow;
  dimensions: ChecklistDimension[];
  open?: boolean;
}) {
  return (
    <details
      open={open}
      className="rounded-md border border-border-muted bg-card"
      data-testid={`checklist-row-${row.ticker}`}
    >
      <summary className="flex cursor-pointer list-none flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
        <span className="min-w-0">
          <span className="ticker font-semibold">{row.ticker}</span>{" "}
          <span className="text-sm text-text-secondary">{row.name}</span>
          <span className="mt-0.5 block text-2xs text-text-tertiary">
            Session {row.session_date}
            {row.stale ? " · older than this venue's latest checklist" : ""}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <ul className="flex flex-wrap gap-1.5" aria-label={`${row.ticker} dimensions`}>
            {dimensions.map((dimension) => {
              const status = resultFor(row, dimension.key)?.status ?? "unknown";
              return (
                <li
                  key={dimension.key}
                  className="inline-flex items-center gap-1 rounded-sm border border-border-muted px-1.5 py-0.5 text-2xs"
                >
                  <span className="text-text-tertiary">{dimension.name}:</span>
                  <span className={status === "met" ? "font-semibold" : "text-text-secondary"}>
                    {STATUS_LABEL[status]}
                  </span>
                </li>
              );
            })}
          </ul>
          <span className="flex flex-col items-start md:items-end">
            <StrengthDots score={row.met} max={row.total} />
            <span className="text-2xs text-text-tertiary">
              {metSummary(row)} ({evaluatedNote(row)})
            </span>
          </span>
        </span>
      </summary>
      <div className="grid gap-2 border-t border-border-muted p-3 md:grid-cols-2 xl:grid-cols-3">
        {dimensions.map((dimension) => (
          <ResultDetail
            key={dimension.key}
            dimension={dimension}
            result={resultFor(row, dimension.key)}
          />
        ))}
      </div>
    </details>
  );
}
