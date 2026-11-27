/**
 * /filings/[id] — A7.10 (M5.5): one stored document's text, `q` marked.
 * A9.10 (M11.3): what changed since the previous document of its kind, and
 * (signed in, with a model) reported figures checked against the text.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import type { CopilotChoice } from "@/components/copilot/copilot-panel";
import { DocumentMeta, Marked } from "@/components/documents-view";
import { DocumentChanges, FigureExtractor } from "@/components/filing-analysis";
import { PageHeader } from "@/components/page-header";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import { getAiStatus } from "@/lib/api/ai";
import { listAiKeys } from "@/lib/api/ai-server";
import { compareDocument, getDocument } from "@/lib/api/documents";
import { checkVisitorLimit } from "@/lib/visitor-limit";

import { extractFiguresAction } from "./actions";

export const metadata: Metadata = { title: "Filing" };

export default async function FilingPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ q?: string }>;
}) {
  const limit = await checkVisitorLimit("filings");
  if (!limit.allowed) return <VisitorLimitNotice retryAfterSeconds={limit.retryAfterSeconds} />;
  const { id } = await params;
  const q = ((await searchParams).q ?? "").trim().slice(0, 100);
  const num = Number(id);
  if (!Number.isInteger(num) || num <= 0) notFound();
  let detail: Awaited<ReturnType<typeof getDocument>>;
  try {
    detail = await getDocument(num, q || undefined);
  } catch {
    notFound();
  }
  const doc = detail.document;
  const [changes, session, status] = await Promise.all([
    compareDocument(num).catch(() => null),
    auth(),
    getAiStatus().catch(() => null),
  ]);
  const keys = session?.user ? await listAiKeys().catch(() => null) : null;
  const ownKey = keys?.keys.find((k) => k.provider === "openai_compatible");
  const choices: CopilotChoice[] = [
    ...(status?.configured
      ? [{ value: "server" as const, label: `Server: ${status.provider} ${status.model}` }]
      : []),
    ...(ownKey
      ? [{ value: "openai_compatible" as const, label: `Your key: ${ownKey.model}` }]
      : []),
  ];
  return (
    <div className="w-full space-y-4 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader eyebrow="Workbench" title={doc.title} description="" />
      <DocumentMeta doc={doc} />
      <p className="text-xs">
        <Link href={`/filings?ticker=${encodeURIComponent(doc.ticker)}`} className="underline">
          All {doc.ticker} documents
        </Link>
        {doc.url ? (
          <>
            {" · "}
            <a href={doc.url} target="_blank" rel="noreferrer" className="underline">
              Original
            </a>
          </>
        ) : null}
        {detail.matches != null ? ` · ${detail.matches} matches for "${q}"` : null}
      </p>
      {changes ? <DocumentChanges data={changes} /> : null}
      {session?.user && choices.length ? (
        <FigureExtractor documentId={doc.id} choices={choices} extract={extractFiguresAction} />
      ) : null}
      <article
        className="whitespace-pre-wrap rounded-lg border border-border bg-card p-4 text-sm leading-relaxed"
        data-testid="document-text"
      >
        <Marked text={detail.text} q={q} />
      </article>
      {detail.truncated ? (
        <p className="text-2xs text-text-tertiary">Shown up to 400,000 characters.</p>
      ) : null}
    </div>
  );
}
