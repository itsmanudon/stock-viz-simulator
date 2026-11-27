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
import { aiChoices } from "@/lib/ai-choices";
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
  // A8.7: the user's saved keys (OpenAI-compatible, Claude) are further choices.
  const keys: AiKeys | null = session?.user ? await listAiKeys().catch(() => null) : null;
  const choices = aiChoices(status, keys);
  return (
    <PageFrame>
      <PageHeader
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
            {/* Inside redesign (27 Nov 2026): an account holder can't set the
                server's model, but can save a key of their own, so that is the
                way forward; the server's reason stays as a small note. */}
            <PageEmptyState
              title="Connect a Model to Ask"
              action={
                <div className="flex flex-wrap items-center gap-3">
                  <Link
                    href="/settings#ai-keys-heading"
                    className="prism-cta inline-flex h-9 items-center rounded-full px-4 text-sm font-medium"
                  >
                    Add Your AI Key
                  </Link>
                  <Link href="/filings?match=meaning" className="text-sm font-medium underline">
                    Search the passages yourself
                  </Link>
                </div>
              }
            >
              <p>
                No model is set up on this server and you have not saved a key. Save an
                OpenAI-compatible or Claude key in Settings and the copilot answers with it, billed
                to your own account. Every answer cites the passages it used.
              </p>
              <p className="mt-2 text-xs text-text-tertiary">
                Server note: {status?.reason ?? "The AI status could not be read just now."}
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
