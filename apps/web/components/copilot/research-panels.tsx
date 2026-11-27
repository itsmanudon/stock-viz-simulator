"use client";

/**
 * A9.11 on /copilot: the research grid (M11.4) and the case for and against
 * (M11.5). Every answer shows its citations as numbers with the sources it
 * may cite underneath; the API's citation warnings are shown with it.
 */

import Link from "next/link";
import { useId, useState, useTransition } from "react";

import type { DebateState, GridState } from "@/app/(product)/copilot/actions";
import type { CopilotChoice } from "@/components/copilot/copilot-panel";
import { filingHref } from "@/components/documents-view";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AiProviderChoice, CheckedAnswer } from "@/lib/api/ai";
import { answerParts } from "@/lib/copilot";

function ModelSelect({
  choices,
  value,
  onChange,
}: {
  choices: CopilotChoice[];
  value: AiProviderChoice;
  onChange: (v: AiProviderChoice) => void;
}) {
  const id = useId();
  if (choices.length < 2) return null;
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">
        Model
      </Label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as AiProviderChoice)}
        className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
      >
        {choices.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** One checked answer: text with citation chips, warnings, its sources. */
export function CheckedAnswerView({ result, testId }: { result: CheckedAnswer; testId: string }) {
  const parts = answerParts(result.answer, result.sources.length);
  return (
    <div className="space-y-2" data-testid={testId} data-grounded={result.grounded}>
      <p className="text-sm leading-relaxed">
        {parts.map((p, i) =>
          p.kind === "text" ? (
            // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
            <span key={i}>{p.text}</span>
          ) : (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
              key={i}
              className={
                p.valid
                  ? "mx-0.5 rounded bg-brand/20 px-1 font-mono text-2xs"
                  : "mx-0.5 rounded border border-warning px-1 font-mono text-2xs text-warning"
              }
            >
              [{p.n}
              {p.valid ? "" : "?"}]
            </span>
          ),
        )}
      </p>
      {result.warnings.map((w) => (
        <p key={w} className="text-2xs text-warning">
          {w}
        </p>
      ))}
      {result.sources.length ? (
        <details>
          <summary className="cursor-pointer text-2xs text-text-tertiary">
            {result.sources.length} source{result.sources.length === 1 ? "" : "s"}
          </summary>
          <ol className="mt-1 space-y-1">
            {result.sources.map((s) => (
              <li key={s.n} className="text-2xs text-text-secondary">
                [{s.n}]{" "}
                <Link href={filingHref(s.passage.document.id)} className="underline">
                  {s.passage.document.title}
                </Link>
                {s.cited ? "" : " (not cited)"}: {s.passage.text}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

export function GridPanel({
  choices,
  run,
}: {
  choices: CopilotChoice[];
  run: (tickers: string, questions: string[], provider: AiProviderChoice) => Promise<GridState>;
}) {
  const tId = useId();
  const [tickers, setTickers] = useState("");
  const [questions, setQuestions] = useState(["", "", ""]);
  const [provider, setProvider] = useState<AiProviderChoice>(choices[0]?.value ?? "server");
  const [state, setState] = useState<GridState>({});
  const [pending, start] = useTransition();
  const grid = state.grid;
  return (
    <div className="space-y-4" data-testid="grid-panel">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          start(async () => setState(await run(tickers, questions, provider)));
        }}
      >
        <div className="space-y-1">
          <Label htmlFor={tId} className="text-xs">
            Symbols (Up to 5)
          </Label>
          <Input
            id={tId}
            value={tickers}
            onChange={(e) => setTickers(e.target.value.toUpperCase())}
            placeholder="TCS.NS, INFY.NS"
          />
        </div>
        {questions.map((q, i) => (
          <div key={`q${i + 1}`} className="space-y-1">
            <Label htmlFor={`${tId}-q${i}`} className="text-xs">
              Question {i + 1}
              {i > 0 ? " (Optional)" : ""}
            </Label>
            <Input
              id={`${tId}-q${i}`}
              value={q}
              maxLength={300}
              onChange={(e) =>
                setQuestions(questions.map((old, j) => (j === i ? e.target.value : old)))
              }
              placeholder={i === 0 ? "What did management say about margins?" : ""}
            />
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-2">
          <ModelSelect choices={choices} value={provider} onChange={setProvider} />
          <Button type="submit" disabled={pending}>
            {pending ? "Reading the Sources…" : "Build Grid"}
          </Button>
        </div>
        <p className="text-2xs text-text-tertiary">
          Each cell is one answer from that company's documents only: up to 15 model calls.
        </p>
      </form>
      {state.error ? (
        <p role="alert" className="text-sm text-negative">
          {state.error}
        </p>
      ) : null}
      {grid ? (
        <div className="space-y-2" data-testid="grid-result">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] border-collapse text-left">
              <thead>
                <tr>
                  <th className="border-b border-border p-2 text-xs">Symbol</th>
                  {grid.questions.map((q) => (
                    <th key={q} className="border-b border-border p-2 text-xs font-medium">
                      {q}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {grid.tickers.map((t) => (
                  <tr key={t} className="align-top">
                    <th className="ticker border-b border-border-muted p-2 text-xs font-semibold">
                      {t}
                    </th>
                    {grid.questions.map((q) => {
                      const cell = grid.cells.find((c) => c.ticker === t && c.question === q);
                      return (
                        <td key={q} className="border-b border-border-muted p-2">
                          {cell ? (
                            <CheckedAnswerView result={cell.result} testId="grid-cell" />
                          ) : (
                            "—"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-2xs text-text-tertiary">
            {grid.provider} {grid.model} · {grid.model_calls} model call
            {grid.model_calls === 1 ? "" : "s"}. {grid.disclaimer}
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function DebatePanel({
  choices,
  run,
}: {
  choices: CopilotChoice[];
  run: (ticker: string, topic: string, provider: AiProviderChoice) => Promise<DebateState>;
}) {
  const tId = useId();
  const pId = useId();
  const [ticker, setTicker] = useState("");
  const [topic, setTopic] = useState("");
  const [provider, setProvider] = useState<AiProviderChoice>(choices[0]?.value ?? "server");
  const [state, setState] = useState<DebateState>({});
  const [pending, start] = useTransition();
  const d = state.debate;
  return (
    <div className="space-y-4" data-testid="debate-panel">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          start(async () => setState(await run(ticker, topic, provider)));
        }}
      >
        <div className="space-y-1">
          <Label htmlFor={tId} className="text-xs">
            Symbol
          </Label>
          <Input
            id={tId}
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="TCS.NS"
            className="w-32"
          />
        </div>
        <div className="min-w-64 flex-1 space-y-1">
          <Label htmlFor={pId} className="text-xs">
            Topic
          </Label>
          <Input
            id={pId}
            value={topic}
            maxLength={300}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Growth, margins and demand outlook"
          />
        </div>
        <ModelSelect choices={choices} value={provider} onChange={setProvider} />
        <Button type="submit" disabled={pending}>
          {pending ? "Reading the Sources…" : "Argue Both Sides"}
        </Button>
      </form>
      {state.error ? (
        <p role="alert" className="text-sm text-negative">
          {state.error}
        </p>
      ) : null}
      {d ? (
        <div className="space-y-3" data-testid="debate-result">
          <div className="grid gap-3 md:grid-cols-2">
            <section className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">Case For</h2>
              <CheckedAnswerView result={d.case_for} testId="case-for" />
            </section>
            <section className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">Case Against</h2>
              <CheckedAnswerView result={d.case_against} testId="case-against" />
            </section>
          </div>
          <p className="text-2xs text-text-tertiary">
            Both sides were argued by {d.provider} {d.model} from the same passages. {d.disclaimer}
          </p>
        </div>
      ) : null}
    </div>
  );
}
