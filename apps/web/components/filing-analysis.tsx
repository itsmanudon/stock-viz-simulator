"use client";

/**
 * A9.10 (M11.3) on /filings/[id]: `FigureExtractor` asks the model for the
 * document's reported figures; only those the API verified against the text
 * arrive, each shown with its quote, and the dropped ones are counted.
 * `DocumentChanges` (server-renderable) shows what changed since an earlier
 * document: counts, hedging per 1,000 words and the changed paragraphs.
 */

import { useId, useState, useTransition } from "react";

import type { ExtractState } from "@/app/(product)/filings/[id]/actions";
import type { CopilotChoice } from "@/components/copilot/copilot-panel";
import { Button } from "@/components/ui/button";
import type { AiProviderChoice } from "@/lib/api/ai";
import type { DocumentCompare } from "@/lib/api/documents";

export function hedgingLine(c: DocumentCompare): string | null {
  const a = c.hedging_after?.per_thousand;
  const b = c.hedging_before?.per_thousand;
  if (a == null) return null;
  if (b == null || !c.against) return `Hedging words: ${a} per 1,000 words.`;
  const diff = Math.round((a - b) * 100) / 100;
  const sign = diff > 0 ? "+" : "";
  return `Hedging words: ${b} → ${a} per 1,000 words (${sign}${diff}).`;
}

export function DocumentChanges({ data }: { data: DocumentCompare }) {
  const hedge = hedgingLine(data);
  return (
    <section
      className="space-y-3 rounded-lg border border-border bg-card p-4"
      data-testid="document-changes"
    >
      <h2 className="text-sm font-semibold">What Changed</h2>
      <p className="text-xs text-text-secondary">{data.note}</p>
      {data.against ? (
        <p className="text-sm" data-testid="document-change-counts">
          {data.scope === "risk_factors" ? "Risk factors: " : "Whole text: "}
          {data.added} added · {data.removed} removed · {data.changed} reworded · {data.unchanged}{" "}
          unchanged
        </p>
      ) : null}
      {data.scope_note ? <p className="text-2xs text-text-tertiary">{data.scope_note}</p> : null}
      {hedge ? (
        <p className="text-xs text-text-secondary" data-testid="document-hedging">
          {hedge}
        </p>
      ) : null}
      {data.changes.length ? (
        <details>
          <summary className="cursor-pointer text-xs font-medium">
            Show the {data.changes.length} changed paragraphs
            {data.truncated ? " (first 60)" : ""}
          </summary>
          <ul className="mt-2 space-y-2">
            {data.changes.map((c, i) => (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: changes are positional
                key={i}
                className="rounded-md border border-border-muted p-2 text-xs"
                data-testid="document-change"
                data-kind={c.kind}
              >
                <p className="mb-1 font-medium">
                  {c.kind === "added" ? "Added" : c.kind === "removed" ? "Removed" : "Reworded"}
                  {c.similarity != null ? ` · ${Math.round(c.similarity * 100)}% Similar` : ""}
                </p>
                {c.before ? (
                  <p className="text-text-tertiary">
                    <span className="sr-only">Before: </span>
                    {c.before}
                  </p>
                ) : null}
                {c.after ? (
                  <p className="mt-1 text-text-secondary">
                    <span className="sr-only">After: </span>
                    {c.after}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="text-2xs text-text-tertiary">{data.method}</p>
    </section>
  );
}

export function FigureExtractor({
  documentId,
  choices,
  extract,
}: {
  documentId: number;
  choices: CopilotChoice[];
  extract: (id: number, provider: AiProviderChoice) => Promise<ExtractState>;
}) {
  const id = useId();
  const [provider, setProvider] = useState<AiProviderChoice>(choices[0]?.value ?? "server");
  const [state, setState] = useState<ExtractState>({});
  const [pending, start] = useTransition();
  const result = state.result;
  const dropped = result ? Object.entries(result.dropped) : [];
  return (
    <section
      className="space-y-3 rounded-lg border border-border bg-card p-4"
      data-testid="figure-extractor"
    >
      <h2 className="text-sm font-semibold">Reported Figures</h2>
      <div className="flex flex-wrap items-end gap-2">
        {choices.length > 1 ? (
          <label htmlFor={id} className="space-y-1 text-xs">
            <span className="block">Model</span>
            <select
              id={id}
              value={provider}
              onChange={(e) => setProvider(e.target.value as AiProviderChoice)}
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
            >
              {choices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={pending}
          onClick={() => start(async () => setState(await extract(documentId, provider)))}
        >
          {pending ? "Reading…" : "Extract Figures"}
        </Button>
      </div>
      {state.error ? (
        <p role="alert" className="text-xs text-negative">
          {state.error}
        </p>
      ) : null}
      {result ? (
        <div className="space-y-2" data-testid="figures">
          {result.figures.length === 0 ? (
            <p className="text-xs text-text-secondary">
              No figure could be checked against the text.
            </p>
          ) : (
            <ul className="space-y-2">
              {result.figures.map((f) => (
                <li
                  key={`${f.metric}-${f.value}`}
                  className="rounded-md border border-border-muted p-2"
                  data-testid="figure"
                >
                  <p className="text-sm">
                    <span className="font-medium">{f.metric}</span>{" "}
                    <span className="font-mono">{f.value}</span>
                    {f.unit ? ` ${f.unit}` : ""}
                    {f.period ? <span className="text-text-tertiary"> · {f.period}</span> : null}
                  </p>
                  <p className="text-xs text-text-secondary">“{f.quote}”</p>
                </li>
              ))}
            </ul>
          )}
          {dropped.length ? (
            <p className="text-2xs text-text-tertiary" data-testid="figures-dropped">
              Dropped: {dropped.map(([why, n]) => `${n} (${why})`).join(", ")}.
            </p>
          ) : null}
          <p className="text-2xs text-text-tertiary">
            {result.model
              ? `${result.provider} ${result.model} read ${result.passages_read} passages. `
              : ""}
            {result.method}
          </p>
          <p className="text-2xs text-text-tertiary">{result.disclaimer}</p>
        </div>
      ) : null}
    </section>
  );
}
