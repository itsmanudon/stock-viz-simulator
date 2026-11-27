"use client";

/**
 * A8.2 (M4.2): describe a screen in words; the server's model drafts Rule DSL
 * and the rule checker judges it. The draft is shown as text with its check;
 * "Use This Rule" puts it in the editor, where the usual check runs again.
 * Nothing runs on a draft.
 */

import { useId, useState, useTransition } from "react";

import type { RuleDraftState } from "@/app/(product)/screener/actions";
import { Button } from "@/components/ui/button";

export function RuleDraft({
  model,
  draft,
  onRule,
}: {
  model: string;
  draft: (text: string) => Promise<RuleDraftState>;
  onRule: (rule: string) => void;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [state, setState] = useState<RuleDraftState>({});
  const [pending, start] = useTransition();
  return (
    <div className="mt-2 space-y-2" data-testid="rule-draft">
      <label htmlFor={id} className="block text-text-tertiary">
        Describe the screen; {model} drafts a rule for you to read.
      </label>
      <textarea
        id={id}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        maxLength={500}
        placeholder="Above the 200-day average with RSI under 40"
        className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm"
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={pending || text.trim().length < 3}
        onClick={() => start(async () => setState(await draft(text)))}
      >
        {pending ? "Drafting…" : "Draft Rule"}
      </Button>
      {state.rule ? (
        <div
          className="space-y-1 rounded-md border border-border p-2"
          data-testid="rule-draft-result"
        >
          <code className="block break-words font-mono text-xs text-foreground">{state.rule}</code>
          <p className="text-2xs" data-testid="rule-draft-check">
            {state.valid ? "Passes the rule check." : `Fails the rule check: ${state.error}`}
          </p>
          {state.valid ? (
            <Button type="button" size="sm" onClick={() => onRule(state.rule ?? "")}>
              Use This Rule
            </Button>
          ) : null}
          {state.note ? <p className="text-2xs text-text-tertiary">{state.note}</p> : null}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-xs text-negative">
          {state.error}
        </p>
      ) : null}
    </div>
  );
}
