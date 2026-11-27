"use client";

/**
 * A8.5 (M11.2): ask the stored filings and transcripts. The answer is the
 * model's text with each citation as a link to its passage below; citations
 * of sources that do not exist are marked, and the API's warnings are shown
 * above the sources. Nothing is stored.
 */

import Link from "next/link";
import { useId, useState, useTransition } from "react";

import type { CopilotState } from "@/app/(product)/copilot/actions";
import { DocumentMeta, filingHref } from "@/components/documents-view";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AiProviderChoice, CopilotAnswer } from "@/lib/api/ai";
import { answerParts, questionProblem } from "@/lib/copilot";

export function CopilotAnswerView({ answer }: { answer: CopilotAnswer }) {
  const parts = answerParts(answer.answer, answer.sources.length);
  return (
    <section className="space-y-4" data-testid="copilot-answer" data-grounded={answer.grounded}>
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="text-sm leading-relaxed text-foreground" data-testid="copilot-answer-text">
          {parts.map((p, i) =>
            p.kind === "text" ? (
              // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
              <span key={i}>{p.text}</span>
            ) : p.valid ? (
              <a
                // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
                key={i}
                href={`#source-${p.n}`}
                className="mx-0.5 rounded bg-brand/20 px-1 font-mono text-2xs text-foreground"
                data-testid="copilot-cite"
              >
                [{p.n}]
              </a>
            ) : (
              <span
                // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
                key={i}
                title="This source does not exist"
                className="mx-0.5 rounded border border-warning px-1 font-mono text-2xs text-warning"
                data-testid="copilot-cite-invalid"
              >
                [{p.n}?]
              </span>
            ),
          )}
        </p>
        <p className="mt-2 text-2xs text-text-tertiary">
          {answer.model ? `${answer.provider} ${answer.model} · ` : ""}
          Passages ranked by {answer.retrieval_mode === "hybrid" ? "words and meaning" : "words"}
        </p>
      </div>
      {answer.warnings.length ? (
        <ul className="space-y-1" data-testid="copilot-warnings">
          {answer.warnings.map((w) => (
            <li key={w} className="text-xs text-warning">
              {w}
            </li>
          ))}
        </ul>
      ) : null}
      {answer.sources.length ? (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Sources the Model Saw</h2>
          <ol className="space-y-2">
            {answer.sources.map((s) => (
              <li
                key={s.n}
                id={`source-${s.n}`}
                className="rounded-lg border border-border bg-card p-3"
                data-testid="copilot-source"
                data-cited={s.cited}
              >
                <p className="text-xs font-medium">
                  [{s.n}]{" "}
                  <Link href={filingHref(s.passage.document.id)} className="hover:underline">
                    {s.passage.document.title}
                  </Link>
                  {s.cited ? null : <span className="ml-2 text-text-tertiary">Not Cited</span>}
                </p>
                <DocumentMeta doc={s.passage.document} />
                <p className="mt-1 whitespace-pre-line text-xs text-text-secondary">
                  {s.passage.text.length > 500
                    ? `${s.passage.text.slice(0, 500)}…`
                    : s.passage.text}
                </p>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {answer.notes.map((n) => (
        <p key={n} className="text-2xs text-text-tertiary">
          {n}
        </p>
      ))}
      <p className="text-2xs text-text-tertiary" data-testid="copilot-disclaimer">
        {answer.disclaimer}
      </p>
    </section>
  );
}

export type CopilotChoice = { value: AiProviderChoice; label: string };

export function CopilotPanel({
  choices,
  ask,
}: {
  choices: CopilotChoice[];
  ask: (question: string, ticker: string, provider: AiProviderChoice) => Promise<CopilotState>;
}) {
  const qId = useId();
  const tId = useId();
  const pId = useId();
  const [provider, setProvider] = useState<AiProviderChoice>(choices[0]?.value ?? "server");
  const model = choices.find((c) => c.value === provider)?.label ?? "The model";
  const [question, setQuestion] = useState("");
  const [ticker, setTicker] = useState("");
  const [state, setState] = useState<CopilotState>({});
  const [pending, start] = useTransition();
  const problem = questionProblem(question);
  const submit = () => {
    if (problem || pending) return;
    start(async () => setState(await ask(question, ticker, provider)));
  };
  return (
    <div className="space-y-4" data-testid="copilot-panel">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="space-y-1">
          <Label htmlFor={qId} className="text-xs">
            Question
          </Label>
          <textarea
            id={qId}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
            }}
            rows={3}
            maxLength={500}
            placeholder="What did management say about margins?"
            className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
          />
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor={tId} className="text-xs">
              Symbol (Optional)
            </Label>
            <Input
              id={tId}
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="TCS.NS"
              className="w-32"
            />
          </div>
          {choices.length > 1 ? (
            <div className="space-y-1">
              <Label htmlFor={pId} className="text-xs">
                Model
              </Label>
              <select
                id={pId}
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
            </div>
          ) : null}
          <Button type="submit" disabled={pending || problem !== null}>
            {pending ? "Reading the Sources…" : "Ask"}
          </Button>
        </div>
        <p className="text-2xs text-text-tertiary">
          {model} answers only from passages of the documents stored here, and cites each one.
          {provider === "openai_compatible" ? " Billed to your account with that provider." : ""}
        </p>
      </form>
      {state.error ? (
        <p role="alert" className="text-sm text-negative">
          {state.error}
        </p>
      ) : null}
      {state.answer ? <CopilotAnswerView answer={state.answer} /> : null}
    </div>
  );
}
