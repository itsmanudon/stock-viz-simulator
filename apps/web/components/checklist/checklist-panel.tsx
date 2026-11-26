import Link from "next/link";

import { GradeBadge } from "@/components/checklist/checklist-view";
import { StrengthDots } from "@/components/strength-dots";
import type { SymbolChecklist } from "@/lib/api/types";
import {
  STATUS_LABEL,
  evaluatedNote,
  metSummary,
  resultFor,
  variantFor,
} from "@/lib/checklist-view";

/**
 * The stock page's compact Checklist (A2.4): the six dimensions with their
 * status and grade, the count, the session, and a link to the full page.
 * The page leaves it out when the call failed.
 */
export function ChecklistPanel({ checklist }: { checklist: SymbolChecklist }) {
  const row = checklist.row ?? null;
  return (
    <section
      aria-labelledby="stock-checklist"
      className="border-y border-border-muted py-5"
      data-testid="stock-checklist"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="stock-checklist" className="text-base font-semibold">
          Checklist
        </h3>
        {row ? (
          <span className="flex items-center gap-2 text-xs text-text-secondary">
            <StrengthDots score={row.met} max={row.total} />
            <span>
              {metSummary(row)} · {evaluatedNote(row)} · session {row.session_date}
            </span>
          </span>
        ) : null}
      </div>
      {row ? (
        <ul className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          {checklist.dimensions.map((dimension) => {
            const result = resultFor(row, dimension.key);
            const status = result?.status ?? "unknown";
            return (
              <li key={dimension.key} className="flex items-center justify-between gap-2 text-sm">
                <span className="text-text-secondary">{dimension.name}</span>
                <span className="flex items-center gap-2">
                  <span className={status === "met" ? "font-semibold" : "text-text-tertiary"}>
                    {STATUS_LABEL[status]}
                  </span>
                  <GradeBadge evidence={variantFor(dimension, result)?.evidence} />
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          Not scored yet: the nightly checklist has not judged {checklist.ticker}.
        </p>
      )}
      <p className="mt-3 text-xs leading-5 text-text-tertiary">
        Six published conditions, not a recommendation.{" "}
        <Link href={`/checklist?q=${checklist.ticker}`} className="text-foreground hover:underline">
          Formulas and evidence
        </Link>
      </p>
    </section>
  );
}
