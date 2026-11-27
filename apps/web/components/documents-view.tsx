/**
 * A7.10 (M5.5): stored filings and transcripts. Server-renderable pieces for
 * /filings (list or search results) and /filings/[id] (the text, with the
 * searched phrase marked). Every date says when the document became public.
 */

import Link from "next/link";

import { formatUtcDateTime } from "@/lib/api-time";
import type { DocumentItem } from "@/lib/api/documents";
import { kindLabel } from "@/lib/api/documents";

export function filingHref(id: number, q?: string): string {
  return q ? `/filings/${id}?q=${encodeURIComponent(q)}` : `/filings/${id}`;
}

export function DocumentMeta({ doc }: { doc: DocumentItem }) {
  return (
    <p className="text-2xs text-text-tertiary" data-testid="document-meta">
      <span className="ticker font-semibold">{doc.ticker}</span> · {kindLabel(doc.kind)}
      {doc.form_type ? ` · ${doc.form_type}` : null} · Public {formatUtcDateTime(doc.available_at)}
      {doc.available_assumed ? " (Assumed: End of Its Date)" : null} ·{" "}
      {doc.source === "edgar" ? "SEC EDGAR" : "Placed by Hand"}
    </p>
  );
}

export function DocumentRow({
  doc,
  q,
  matches,
  snippets,
}: {
  doc: DocumentItem;
  q?: string;
  matches?: number;
  snippets?: string[];
}) {
  return (
    <li className="rounded-lg border border-border bg-card p-3" data-testid="document-row">
      <Link href={filingHref(doc.id, q)} className="text-sm font-medium hover:underline">
        {doc.title}
      </Link>
      <DocumentMeta doc={doc} />
      {matches != null ? (
        <p className="mt-1 text-xs text-text-secondary" data-testid="document-matches">
          {matches === 1 ? "1 Match" : `${matches} Matches`}
        </p>
      ) : null}
      {snippets?.length ? (
        <ul className="mt-2 space-y-1">
          {snippets.map((s) => (
            <li key={s} className="text-xs text-text-secondary">
              <Marked text={s} q={q ?? ""} />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Split ``text`` around case-insensitive matches of ``q`` (pure, for tests). */
export function markParts(text: string, q: string): { text: string; hit: boolean }[] {
  const needle = q.trim();
  if (!needle) return [{ text, hit: false }];
  const lower = text.toLowerCase();
  const n = needle.toLowerCase();
  const parts: { text: string; hit: boolean }[] = [];
  let at = 0;
  for (let i = lower.indexOf(n); i !== -1; i = lower.indexOf(n, at)) {
    if (i > at) parts.push({ text: text.slice(at, i), hit: false });
    parts.push({ text: text.slice(i, i + n.length), hit: true });
    at = i + n.length;
  }
  if (at < text.length) parts.push({ text: text.slice(at), hit: false });
  return parts;
}

export function Marked({ text, q }: { text: string; q: string }) {
  return (
    <>
      {markParts(text, q).map((p, i) =>
        p.hit ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
          <mark key={i} className="rounded bg-brand/25 px-0.5 text-foreground">
            {p.text}
          </mark>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
