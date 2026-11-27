/**
 * /copilot — A8.5 (M11.2): ask the stored filings and transcripts.
 *
 * Public page; asking needs a sign-in and a model on the server (A8.3:
 * `OLLAMA_MODEL`). Answers come only from A8.4's passages and cite them; the
 * citations are checked by the API and shown with the passages. Nothing is
 * stored.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { auth } from "@/auth";
import { CopilotPanel } from "@/components/copilot/copilot-panel";
import { DebatePanel, GridPanel } from "@/components/copilot/research-panels";
import { PageFrame } from "@/components/page-frame";
import { PageEmptyState, PageHeader } from "@/components/page-header";
import { type AiKeys, type AiStatus, getAiStatus } from "@/lib/api/ai";
import { listAiKeys } from "@/lib/api/ai-server";

import { askCopilotAction, debateAction, gridAction } from "./actions";

export const metadata: Metadata = { title: "AI Copilot" };

const MODES = [
  { value: "ask", label: "Ask" },
  { value: "grid", label: "Grid" },
  { value: "debate", label: "For and Against" },
] as const;

export default async function CopilotPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string }>;
}) {
  const raw = (await searchParams).mode;
  const mode = MODES.find((m) => m.value === raw)?.value ?? "ask";
  const session = await auth();
  let status: AiStatus | null = null;
  try {
    status = await getAiStatus();
  } catch {
    status = null;
  }
  // A8.7: the user's own OpenAI-compatible key, if saved, is a second choice.
  const keys: AiKeys | null = session?.user ? await listAiKeys().catch(() => null) : null;
  const ownKey = keys?.keys.find((k) => k.provider === "openai_compatible") ?? null;
  const choices = [
    ...(status?.configured
      ? [{ value: "server" as const, label: `Server: ${status.provider} ${status.model}` }]
      : []),
    ...(ownKey
      ? [{ value: "openai_compatible" as const, label: `Your key: ${ownKey.model}` }]
      : []),
  ];
  return (
    <PageFrame>
      <PageHeader
        eyebrow="AI Copilot"
        title="Copilot"
        description="Ask the filings and transcripts stored here. Every answer cites the passages it came from."
      />
      <div className="mt-6 max-w-3xl">
        {!session?.user ? (
          <div data-testid="copilot-signed-out">
            <PageEmptyState title="Sign In to Ask">
              <p>
                The copilot answers as your account.{" "}
                <Link href="/login?callbackUrl=/copilot" className="font-medium underline">
                  Sign in
                </Link>{" "}
                to ask. You can search the documents themselves on{" "}
                <Link href="/filings" className="font-medium underline">
                  Filings
                </Link>
                .
              </p>
            </PageEmptyState>
          </div>
        ) : choices.length === 0 ? (
          <div data-testid="copilot-off">
            <PageEmptyState title="No Model on This Server">
              <p>
                {status?.reason ?? "The AI status could not be read just now."} Until then,{" "}
                <Link href="/filings?match=meaning" className="font-medium underline">
                  search the passages
                </Link>{" "}
                yourself.
              </p>
            </PageEmptyState>
          </div>
        ) : (
          <div className="space-y-4">
            <nav aria-label="Copilot modes" className="flex gap-2" data-testid="copilot-modes">
              {MODES.map((m) => (
                <Link
                  key={m.value}
                  href={m.value === "ask" ? "/copilot" : `/copilot?mode=${m.value}`}
                  aria-current={mode === m.value ? "page" : undefined}
                  className={`rounded-full border px-3 py-1 text-xs ${
                    mode === m.value
                      ? "border-brand text-foreground"
                      : "border-border text-text-secondary"
                  }`}
                >
                  {m.label}
                </Link>
              ))}
            </nav>
            {mode === "grid" ? (
              <GridPanel choices={choices} run={gridAction} />
            ) : mode === "debate" ? (
              <DebatePanel choices={choices} run={debateAction} />
            ) : (
              <CopilotPanel choices={choices} ask={askCopilotAction} />
            )}
          </div>
        )}
      </div>
    </PageFrame>
  );
}
