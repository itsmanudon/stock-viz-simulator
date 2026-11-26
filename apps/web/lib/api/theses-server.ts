import "server-only";

import type { components } from "./schema";
import { authedGet, authedPatch, authedPost } from "./server";

/** A2.2 theses with A7.5's kill switch (a linked rule alert, judged nightly). */
export type Thesis = components["schemas"]["ThesisOut"];

export function listTheses(): Promise<Thesis[]> {
  return authedGet<Thesis[]>("/v1/theses");
}

export function createThesis(input: {
  ticker: string;
  title: string;
  body: string;
  kill_rule?: string | null;
}): Promise<Thesis> {
  return authedPost<Thesis>("/v1/theses", input);
}

export function updateThesis(
  id: number,
  input: { title?: string; body?: string; kill_rule?: string | null },
): Promise<Thesis> {
  return authedPatch<Thesis>(`/v1/theses/${id}`, input);
}

export function closeThesis(id: number, status: "closed" | "invalidated"): Promise<Thesis> {
  return authedPost<Thesis>(`/v1/theses/${id}/close`, { status });
}
