/**
 * /filings — A7.10 (M5.5): stored filings, annual reports and concall
 * transcripts. `ticker` lists a symbol's documents; `q` searches the text
 * (exact phrase), or with `match=meaning` returns ranked passages (A8.4:
 * full text plus embeddings when the server has a model); `kind` filters.
 * Public, visitor-limited like /news.
 */

import type { Metadata } from "next";

import { DocumentRow, PassageRow } from "@/components/documents-view";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import {
  DOCUMENT_KINDS,
  type DocumentList,
  type DocumentSearch,
  type PassageSearch,
  listDocuments,
  searchDocuments,
  searchPassages,
} from "@/lib/api/documents";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export const metadata: Metadata = { title: "Filings" };

type Search = { ticker?: string; q?: string; kind?: string; match?: string };

export default async function FilingsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const limit = await checkVisitorLimit("filings");
  if (!limit.allowed) return <VisitorLimitNotice retryAfterSeconds={limit.retryAfterSeconds} />;
  const raw = await searchParams;
  const ticker = (raw.ticker ?? "").trim().toUpperCase().slice(0, 16);
  const q = (raw.q ?? "").trim().slice(0, 100);
  const kind = DOCUMENT_KINDS.some((k) => k.value === raw.kind) ? raw.kind : undefined;
  let list: DocumentList | null = null;
  const meaning = raw.match === "meaning";
  let found: DocumentSearch | null = null;
  let passages: PassageSearch | null = null;
  let error: string | null = null;
  try {
    if (q.length >= 2 && meaning) passages = await searchPassages(q, ticker || undefined, kind);
    else if (q.length >= 2) found = await searchDocuments(q, ticker || undefined, kind);
    else if (ticker) list = await listDocuments(ticker, kind);
  } catch (err) {
    error =
      err instanceof Error && /404/.test(err.message)
        ? "That symbol is not stored."
        : "The documents could not be loaded just now.";
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Workbench"
        title="Filings"
        description="Filings, annual reports and concall transcripts as stored, each dated by when it became public."
      />
      <form method="get" className="flex flex-wrap items-end gap-2" data-testid="filings-form">
        <div className="space-y-1">
          <Label htmlFor="filings-ticker" className="text-xs">
            Symbol
          </Label>
          <Input
            id="filings-ticker"
            name="ticker"
            defaultValue={ticker}
            placeholder="TCS.NS"
            className="w-32"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filings-q" className="text-xs">
            Search Text
          </Label>
          <Input
            id="filings-q"
            name="q"
            defaultValue={q}
            placeholder="order book"
            className="w-56"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filings-kind" className="text-xs">
            Kind
          </Label>
          <select
            id="filings-kind"
            name="kind"
            defaultValue={kind ?? ""}
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          >
            <option value="">All Kinds</option>
            {DOCUMENT_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="filings-match" className="text-xs">
            Match
          </Label>
          <select
            id="filings-match"
            name="match"
            defaultValue={meaning ? "meaning" : ""}
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          >
            <option value="">Exact Phrase</option>
            <option value="meaning">Passages</option>
          </select>
        </div>
        <Button type="submit">Show</Button>
      </form>
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      {passages ? (
        <section className="space-y-3" data-testid="filings-passages">
          <p className="text-sm text-text-secondary">
            {passages.passages.length === 0
              ? `No stored passage matches "${passages.query}".`
              : `${passages.passages.length} passage${passages.passages.length === 1 ? "" : "s"} for "${passages.query}", ${
                  passages.mode === "hybrid"
                    ? `ranked by words and meaning (${passages.embed_model})`
                    : "ranked by words only"
                }.`}
          </p>
          {passages.notes.map((n) => (
            <p key={n} className="text-xs text-text-tertiary">
              {n}
            </p>
          ))}
          <ul className="space-y-2">
            {passages.passages.map((p) => (
              <PassageRow key={p.chunk_id} passage={p} />
            ))}
          </ul>
          <p className="text-2xs text-text-tertiary">{passages.method}</p>
        </section>
      ) : found ? (
        <section className="space-y-3" data-testid="filings-results">
          <p className="text-sm text-text-secondary">
            {found.hits.length === 0
              ? `No stored document contains "${found.query}".`
              : `${found.hits.length} document${found.hits.length === 1 ? "" : "s"} contain "${found.query}".`}
          </p>
          <ul className="space-y-2">
            {found.hits.map((h) => (
              <DocumentRow
                key={h.document.id}
                doc={h.document}
                q={found.query}
                matches={h.matches}
                snippets={h.snippets}
              />
            ))}
          </ul>
          <p className="text-2xs text-text-tertiary">{found.note}</p>
        </section>
      ) : list ? (
        <section className="space-y-3" data-testid="filings-list">
          {list.documents.length === 0 ? (
            <p className="text-sm text-text-secondary" data-testid="filings-empty">
              No documents are stored for {list.ticker} yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {list.documents.map((d) => (
                <DocumentRow key={d.id} doc={d} />
              ))}
            </ul>
          )}
          <p className="text-2xs text-text-tertiary">{list.note}</p>
        </section>
      ) : !error ? (
        <p className="text-sm text-text-secondary" data-testid="filings-intro">
          Enter a symbol to list its documents, or search their text.
        </p>
      ) : null}
    </div>
  );
}
