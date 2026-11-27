/** A7.10 (M5.5): stored company documents, listed and searched point-in-time. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type DocumentItem = components["schemas"]["DocumentOut"];
export type DocumentList = components["schemas"]["DocumentListOut"];
export type DocumentDetail = components["schemas"]["DocumentDetailOut"];
export type DocumentSearch = components["schemas"]["DocumentSearchOut"];
export type PassageSearch = components["schemas"]["PassageSearchOut"];
export type Passage = components["schemas"]["PassageOut"];

const CACHE = { revalidateSeconds: 300, tags: ["documents"] };

export const DOCUMENT_KINDS = [
  { value: "filing", label: "Filing" },
  { value: "annual_report", label: "Annual Report" },
  { value: "concall_transcript", label: "Concall Transcript" },
  { value: "announcement", label: "Announcement" },
  { value: "other", label: "Other" },
] as const;

export function kindLabel(kind: string): string {
  return DOCUMENT_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

function query(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listDocuments(ticker: string, kind?: string): Promise<DocumentList> {
  return apiGet<DocumentList>(
    `/v1/symbols/${encodeURIComponent(ticker)}/documents${query({ kind })}`,
    CACHE,
  );
}

export function searchDocuments(
  q: string,
  ticker?: string,
  kind?: string,
): Promise<DocumentSearch> {
  return apiGet<DocumentSearch>(`/v1/documents/search${query({ q, ticker, kind })}`, CACHE);
}

/** A8.4 (M11.1): passages ranked by full text and, when a model is set, meaning. */
export function searchPassages(q: string, ticker?: string, kind?: string): Promise<PassageSearch> {
  return apiGet<PassageSearch>(`/v1/documents/passages${query({ q, ticker, kind })}`, CACHE);
}

export function getDocument(id: number, q?: string): Promise<DocumentDetail> {
  return apiGet<DocumentDetail>(`/v1/documents/${id}${query({ q })}`, CACHE);
}
